"""Localhost-only guards: Host check (DNS rebinding), Origin + CSRF token on POSTs."""
import re
import secrets

from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from starlette.responses import PlainTextResponse

from tally import db, repo
from tally.config import Config

CSRF_KEY = "csrf_secret"
_HOST = re.compile(r"^(127\.0\.0\.1|localhost)(:\d+)?$", re.IGNORECASE)


def host_allowed(host: str | None) -> bool:
    return bool(host and _HOST.match(host))


def allowed_origins(cfg: Config) -> set[str]:
    return {f"http://127.0.0.1:{cfg.dash_port}", f"http://localhost:{cfg.dash_port}"}


def ensure_csrf_secret(conn) -> str:
    secret = repo.get_setting(conn, CSRF_KEY)
    if not secret:
        secret = secrets.token_urlsafe(32)
        repo.set_setting(conn, CSRF_KEY, secret)
    return secret


def _read_secret(cfg: Config) -> str:
    conn = db.connect(cfg.db_path)
    try:
        return ensure_csrf_secret(conn)
    finally:
        conn.close()


async def host_middleware(request: Request, call_next):
    if not host_allowed(request.headers.get("host")):
        return PlainTextResponse("Bad host", status_code=400)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'")
    return response


def make_csrf_guard(cfg: Config):
    origins = allowed_origins(cfg)

    async def csrf_guard(request: Request) -> None:
        origin = request.headers.get("origin")
        if origin is not None and origin not in origins:
            raise HTTPException(403, "Bad origin")
        form = await request.form()
        token = form.get("csrf")
        secret = await run_in_threadpool(_read_secret, cfg)
        if not isinstance(token, str) or not secrets.compare_digest(
                token.encode(), secret.encode()):
            raise HTTPException(403, "Bad CSRF token")

    return csrf_guard
