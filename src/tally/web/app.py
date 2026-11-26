"""Local dashboard app (127.0.0.1:8765 only)."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from tally import db
from tally.config import Config
from tally.llm import LLMClient, OllamaClient
from tally.web.actions import register_actions
from tally.web.pages import register_pages
from tally.web.security import ensure_csrf_secret, host_middleware

WEB_DIR = Path(__file__).parent


def create_dashboard_app(cfg: Config, llm: LLMClient) -> FastAPI:
    # No CORS middleware on purpose; no API docs routes either.
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.middleware("http")(host_middleware)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=WEB_DIR / "templates")

    conn = db.connect(cfg.db_path)
    try:
        ensure_csrf_secret(conn)
    finally:
        conn.close()

    register_pages(app, cfg, templates)
    register_actions(app, cfg, llm)
    return app


def dev_app() -> FastAPI:
    cfg = Config.from_env()
    return create_dashboard_app(cfg, OllamaClient(cfg.ollama_url, cfg.model))
