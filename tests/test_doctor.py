import dataclasses
from pathlib import Path

from tally import doctor
from tally.doctor import in_icloud_path, non_loopback_listeners

LSOF_LOOPBACK = """COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
ollama  123 u    3u  IPv4 0x1      0t0  TCP 127.0.0.1:11434 (LISTEN)
"""
LSOF_EXPOSED = LSOF_LOOPBACK + "ollama  123 u    4u  IPv6 0x2      0t0  TCP *:11434 (LISTEN)\n"


def test_in_icloud_path():
    h = Path("/Users/u")
    assert in_icloud_path(h / "Documents/Tally", h) and in_icloud_path(h / "Desktop/x", h)
    assert in_icloud_path(h / "Library/Mobile Documents/x", h)
    assert not in_icloud_path(h / "Tally", h)
    assert not in_icloud_path(h / "Documents2", h)


def test_non_loopback_listeners():
    assert non_loopback_listeners(LSOF_LOOPBACK, 11434) == []
    assert non_loopback_listeners("COMMAND\no 1 u 3u IPv6 0 0t0 TCP [::1]:11434 (LISTEN)\n",
                                  11434) == []
    assert non_loopback_listeners(LSOF_EXPOSED, 11434) == ["*"]
    assert non_loopback_listeners("", 11434) == []


def test_checks_never_raise(tmp_config, monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("nope")
    monkeypatch.setattr(doctor.subprocess, "run", boom)
    cfg = dataclasses.replace(tmp_config, ollama_url="http://127.0.0.1:1")
    checks = doctor.run_checks(cfg)
    by = {c.name: c for c in checks}
    assert not by["FileVault on"].ok and "not found" in by["FileVault on"].detail
    assert not by["Ollama listens on loopback only"].ok
