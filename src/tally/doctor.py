import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from tally.config import Config
from tally.llm import LLMUnavailable, OllamaClient

_LOOPBACK = {"127.0.0.1", "[::1]", "localhost"}
_SYNCED_DIRS = ("Desktop", "Documents", "Library/Mobile Documents")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def in_icloud_path(path: Path, home: Path) -> bool:
    """True if path is under a folder macOS may sync to iCloud."""
    p = path.expanduser().resolve(strict=False)
    h = home.resolve(strict=False)
    return any(p.is_relative_to(h / d) for d in _SYNCED_DIRS)


def non_loopback_listeners(lsof_output: str, port: int) -> list[str]:
    """Listening addresses in `lsof -nP -iTCP:<port> -sTCP:LISTEN` output that aren't loopback."""
    found = []
    for m in re.finditer(rf"(\S+):{port}\s+\(LISTEN\)", lsof_output):
        addr = m.group(1)
        if addr not in _LOOPBACK and addr not in found:
            found.append(addr)
    return found


def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        raise RuntimeError(f"{cmd[0]} not found") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{cmd[0]} timed out") from None
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exited {r.returncode}: {(r.stderr or r.stdout).strip()[:100]}")
    return r.stdout


def _check_ollama(cfg: Config) -> Check:
    name = "Ollama reachable with model"
    try:
        OllamaClient(cfg.ollama_url, cfg.model).health()
        return Check(name, True, f"{cfg.model} at {cfg.ollama_url}")
    except LLMUnavailable as e:
        return Check(name, False, str(e))


def _check_loopback_only(cfg: Config) -> Check:
    name = "Ollama listens on loopback only"
    try:
        url = urlsplit(cfg.ollama_url)
        if url.hostname not in ("127.0.0.1", "::1", "localhost"):
            return Check(name, False, f"{cfg.ollama_url} is not on this Mac")
        port = url.port or (443 if url.scheme == "https" else 80)
        # lsof exits 1 when nothing listens; treat that as empty output, not failure.
        r = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode not in (0, 1):
            return Check(name, False, f"lsof exited {r.returncode}: {r.stderr.strip()[:100]}")
        bad = non_loopback_listeners(r.stdout, port)
        if bad:
            return Check(name, False, f"listening on {', '.join(bad)}")
        return Check(name, True, "only loopback" if r.stdout.strip() else "nothing listening")
    except FileNotFoundError:
        return Check(name, False, "lsof not found")
    except Exception as e:
        return Check(name, False, f"could not check: {e}")


def _check_filevault(cfg: Config) -> Check:
    name = "FileVault on"
    try:
        out = _run(["fdesetup", "status"]).strip()
        return Check(name, "On" in out, out)
    except Exception as e:
        return Check(name, False, f"could not check: {e}")


def _check_data_dir(cfg: Config) -> Check:
    name = "Data dir outside synced folders"
    try:
        bad = in_icloud_path(cfg.home, Path.home())
        return Check(name, not bad, f"{cfg.home} is in a synced folder" if bad else str(cfg.home))
    except Exception as e:
        return Check(name, False, f"could not check: {e}")


def run_checks(cfg: Config) -> list[Check]:
    checks = []
    for fn in (_check_ollama, _check_loopback_only, _check_filevault, _check_data_dir):
        try:
            checks.append(fn(cfg))
        except Exception as e:  # a check must never crash the doctor
            checks.append(Check(fn.__name__.removeprefix("_check_"), False, f"error: {e}"))
    return checks
