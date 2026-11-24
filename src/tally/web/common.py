"""Small helpers shared by the dashboard route modules."""
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.responses import RedirectResponse

from tally import db, repo
from tally.config import Config
from tally.web.i18n import LANGS

FLASH_KEY = "flash"


@contextmanager
def session(cfg: Config) -> Iterator:
    """One sqlite connection per request, opened and closed in the worker thread."""
    conn = db.connect(cfg.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_lang(conn) -> str:
    v = repo.get_setting(conn, "lang", "en")
    return v if v in LANGS else "en"


def set_flash(conn, msg: str) -> None:
    repo.set_setting(conn, FLASH_KEY, msg)


def pop_flash(conn) -> str | None:
    msg = repo.get_setting(conn, FLASH_KEY)
    if msg:
        repo.set_setting(conn, FLASH_KEY, "")
    return msg or None


def safe_next(target: str | None, default: str) -> str:
    """Only same-site absolute paths; blocks //host and backslash tricks."""
    if (target and target.startswith("/") and not target.startswith("//")
            and "\\" not in target and "\n" not in target and "\r" not in target):
        return target
    return default


def see_other(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)
