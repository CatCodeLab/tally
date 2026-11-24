from datetime import date

import pytest
from typer.testing import CliRunner

from tally import db, doctor, repo
from tally.cli import app, build_servers
from tally.doctor import Check
from helpers import NoLLM


@pytest.fixture
def runner(tmp_config):
    return CliRunner()


@pytest.fixture
def conn_after(tmp_config):
    return lambda: db.connect(tmp_config.db_path)


def test_cli_add_and_withdraw(runner, conn_after):
    assert runner.invoke(app, ["add", "12.50", "McDonald's", "--date", "2026-11-03",
                               "--category", "food"]).exit_code == 0
    assert runner.invoke(app, ["withdraw", "200", "--date", "2026-11-02"]).exit_code == 0
    c = conn_after()
    assert repo.sum_withdrawals(c, date(2026, 11, 1), date(2026, 11, 30)) == 20000
    e = repo.list_entries(c, repo.Filters(date(2026, 11, 1), date(2026, 11, 30)))[0]
    assert (e.source, e.status, e.amount_cents, e.category) == ("manual", "ok", 1250, "food")


def test_cli_add_defaults(runner, conn_after):
    c = conn_after()
    repo.remember_shop_category(c, "Kiosk", "transport")
    assert runner.invoke(app, ["add", "3", "Kiosk"]).exit_code == 0
    assert runner.invoke(app, ["add", "4", "Unknown"]).exit_code == 0
    es = {e.shop: e for e in repo.list_entries(c, repo.Filters(date.today(), date.today()))}
    assert es["Kiosk"].category == "transport" and es["Unknown"].category == "other"


def test_cli_add_bad_input(runner):
    r = runner.invoke(app, ["add", "5", "X", "--category", "gifts"])
    assert r.exit_code != 0 and "food" in r.output
    assert runner.invoke(app, ["add", "abc", "X"]).exit_code != 0
    assert runner.invoke(app, ["withdraw", "5", "--date", "nope"]).exit_code != 0


def test_cli_scan_llm_down_message(runner, monkeypatch):
    monkeypatch.setenv("TALLY_OLLAMA_URL", "http://127.0.0.1:1")
    r = runner.invoke(app, ["scan"])
    assert r.exit_code == 1 and "ollama serve" in r.output


def test_cli_pair(runner):
    r = runner.invoke(app, ["pair", "--ssid", "HomeNet"])
    assert r.exit_code == 0 and ".local" in r.output and "8766" in r.output
    assert "HomeNet" in r.output
    tok = next(l for l in r.output.splitlines() if l.startswith("Token:"))
    r2 = runner.invoke(app, ["pair", "--regenerate"])
    assert tok not in r2.output and "HomeNet" in r2.output


def test_cli_pair_ssid_unset(runner):
    assert "not set" in runner.invoke(app, ["pair"]).output


def test_build_servers_hosts(tmp_config):
    both = build_servers(tmp_config, NoLLM())
    assert [(s.config.host, s.config.port) for s in both] == [("127.0.0.1", 8765),
                                                              ("0.0.0.0", 8766)]
    assert len(build_servers(tmp_config, NoLLM(), voice=False)) == 1


def test_cli_doctor_exit_codes(runner, monkeypatch):
    monkeypatch.setattr(doctor, "run_checks", lambda cfg: [Check("a", True, "fine")])
    r = runner.invoke(app, ["doctor"])
    assert r.exit_code == 0 and "✓ a" in r.output
    monkeypatch.setattr(doctor, "run_checks", lambda cfg: [Check("a", False, "bad")])
    r = runner.invoke(app, ["doctor"])
    assert r.exit_code == 1 and "✗ a" in r.output


def test_normalize_hostname():
    from tally.cli import normalize_hostname
    assert normalize_hostname("Rans-Mac") == "Rans-Mac.local"
    assert normalize_hostname("Rans-Mac.local") == "Rans-Mac.local"
    assert normalize_hostname("Rans-Mac.lan\n") == "Rans-Mac.local"


def test_bonjour_hostname_fallback(monkeypatch):
    from tally import cli
    def boom(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr(cli.subprocess, "run", boom)
    monkeypatch.setattr(cli.socket, "gethostname", lambda: "box.local")
    assert cli.bonjour_hostname() == "box.local"


def test_serve_exits_when_a_server_fails(tmp_config):
    import asyncio
    import socket as sk
    from tally.cli import _serve
    blocker = sk.socket(); blocker.bind(("127.0.0.1", 0)); blocker.listen()
    import dataclasses
    cfg = dataclasses.replace(tmp_config, dash_port=blocker.getsockname()[1])
    try:
        with pytest.raises(RuntimeError, match="already in use"):
            asyncio.run(asyncio.wait_for(_serve(build_servers(cfg, NoLLM(), voice=False), None), 10))
    finally:
        blocker.close()
