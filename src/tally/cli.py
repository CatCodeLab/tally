import asyncio
import socket
import subprocess
import webbrowser
from datetime import date

import typer
import uvicorn

from tally import categories, db, doctor, ingest, repo
from tally.config import Config
from tally.llm import LLMUnavailable, OllamaClient
from tally.money import parse_amount
from tally.voice_server import create_voice_app
from tally.web.app import create_dashboard_app

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Local cash spending tracker.")


def _llm(cfg: Config) -> OllamaClient:
    return OllamaClient(cfg.ollama_url, cfg.model)


def _amount(s: str) -> int:
    try:
        cents = parse_amount(s)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from None
    if cents <= 0:
        raise typer.BadParameter("amount must be greater than zero")
    return cents


def _date(s: str | None) -> date:
    if not s:
        return date.today()
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise typer.BadParameter(f"{s!r} is not YYYY-MM-DD") from None


@app.command()
def scan() -> None:
    """Process new receipts in the inbox."""
    cfg = Config.from_env()
    conn = db.connect(cfg.db_path)
    try:
        r = ingest.scan_inbox(conn, cfg, _llm(cfg))
    except LLMUnavailable as e:
        typer.echo(str(e))
        raise typer.Exit(1) from None
    finally:
        conn.close()
    typer.echo(f"Added {r.added} · To review {r.review} · "
               f"Card skipped {r.card} · Already seen {r.skipped_files}")
    for err in r.errors:
        typer.echo(f"Error: {err}")
    if r.errors:
        raise typer.Exit(1)


@app.command()
def add(amount: str, shop: str,
        date_: str | None = typer.Option(None, "--date", help="YYYY-MM-DD, default today"),
        category: str | None = typer.Option(None, "--category")) -> None:
    """Add a manual cash entry."""
    cents, d = _amount(amount), _date(date_)
    cfg = Config.from_env()
    conn = db.connect(cfg.db_path)
    try:
        if category is not None and not categories.is_valid(category, conn):
            raise typer.BadParameter(
                f"unknown category {category!r}; choose from: "
                + ", ".join(categories.all_slugs(conn)), param_hint="--category")
        cat = category or repo.confirmed_category(conn, shop) or "other"
        repo.add_entry(conn, repo.Entry(id=None, source="manual", shop=shop, date=d,
                                        amount_cents=cents, category=cat, status="ok"))
    finally:
        conn.close()
    typer.echo(f"Added {shop} {amount} on {d} ({cat})")


@app.command()
def withdraw(amount: str,
             date_: str | None = typer.Option(None, "--date", help="YYYY-MM-DD, default today")
             ) -> None:
    """Record an ATM cash withdrawal."""
    cents, d = _amount(amount), _date(date_)
    cfg = Config.from_env()
    conn = db.connect(cfg.db_path)
    try:
        repo.add_withdrawal(conn, d, cents)
    finally:
        conn.close()
    typer.echo(f"Recorded withdrawal {amount} on {d}")


def build_servers(cfg: Config, llm, voice: bool = True) -> list[uvicorn.Server]:
    """Dashboard on loopback; voice app on all interfaces (phone on the LAN)."""
    servers = [uvicorn.Server(uvicorn.Config(
        create_dashboard_app(cfg, llm), host="127.0.0.1", port=cfg.dash_port,
        log_level="warning"))]
    if voice:
        servers.append(uvicorn.Server(uvicorn.Config(
            create_voice_app(cfg, llm), host="0.0.0.0", port=cfg.voice_port,
            log_level="warning")))
    return servers


async def _serve(servers: list[uvicorn.Server], url: str | None) -> None:
    """Run all servers; if any stops (e.g. port in use), stop the rest and raise."""
    async def open_when_up():
        while not servers[0].started:
            await asyncio.sleep(0.1)
        webbrowser.open(url)

    async def run(server: uvicorn.Server):
        try:  # uvicorn calls sys.exit on bind failure; keep that out of the event loop
            await server.serve()
        except SystemExit:
            pass

    tasks = [asyncio.ensure_future(run(s)) for s in servers]
    opener = asyncio.ensure_future(open_when_up()) if url else None
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        failed = [s for s in servers if not s.started]
        for s in servers:
            s.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        if opener:
            opener.cancel()
    if failed:
        ports = ", ".join(str(s.config.port) for s in failed)
        raise RuntimeError(f"could not start server on port {ports} (already in use?)")


@app.command()
def serve(no_voice: bool = typer.Option(False, "--no-voice"),
          no_open: bool = typer.Option(False, "--no-open")) -> None:
    """Run the dashboard (and the voice endpoint)."""
    cfg = Config.from_env()
    servers = build_servers(cfg, _llm(cfg), voice=not no_voice)
    url = None if no_open else f"http://127.0.0.1:{cfg.dash_port}/"
    typer.echo(f"Dashboard: http://127.0.0.1:{cfg.dash_port}/")
    if not no_voice:
        typer.echo(f"Voice endpoint: http://{bonjour_hostname()}:{cfg.voice_port}/api/voice")
    try:
        asyncio.run(_serve(servers, url))
    except KeyboardInterrupt:
        pass
    except (RuntimeError, SystemExit) as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(1) from None


def normalize_hostname(name: str) -> str:
    """'Foo', 'Foo.local' or 'Foo.lan' -> 'Foo.local'."""
    return name.strip().split(".")[0] + ".local"


def bonjour_hostname() -> str:
    try:
        r = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True,
                           text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return normalize_hostname(r.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    return normalize_hostname(socket.gethostname())


@app.command()
def pair(regenerate: bool = typer.Option(False, "--regenerate"),
         ssid: str | None = typer.Option(None, "--ssid", help="Home Wi-Fi name")) -> None:
    """Show the details the phone shortcut needs."""
    cfg = Config.from_env()
    conn = db.connect(cfg.db_path)
    try:
        token = repo.regenerate_token(conn) if regenerate else repo.get_or_create_token(conn)
        if ssid:
            repo.set_setting(conn, "home_ssid", ssid)
        home_ssid = repo.get_setting(conn, "home_ssid")
    finally:
        conn.close()
    host = bonjour_hostname()
    typer.echo(f"Host: {host}")
    typer.echo(f"Port: {cfg.voice_port}")
    typer.echo(f"Token: {token}")
    typer.echo(f"SSID: {home_ssid or 'not set'}")


@app.command(name="doctor")
def doctor_cmd() -> None:
    """Check the local setup."""
    cfg = Config.from_env()
    checks = doctor.run_checks(cfg)
    for c in checks:
        typer.echo(f"{'✓' if c.ok else '✗'} {c.name}: {c.detail}")
    if not all(c.ok for c in checks):
        raise typer.Exit(1)
