"""The Mac's Bonjour name (what the iPhone Shortcut connects to)."""
import socket
import subprocess


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
