"""LAN voice endpoint: token-protected POST /api/voice, nothing else."""
import secrets

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from tally import db, repo
from tally.config import Config
from tally.llm import LLMClient
from tally.voice import VoiceItem, VoiceResult, handle_voice_batch

MAX_BODY = 256 * 1024


class VoiceBatch(BaseModel):
    items: list[VoiceItem] = Field(min_length=1, max_length=200)


def _bearer(header: str | None) -> str | None:
    if not header:
        return None
    parts = header.split(" ")
    if len(parts) != 2 or parts[0] != "Bearer" or not parts[1]:
        return None
    return parts[1]


def _suffix(results: list[VoiceResult], lang: str) -> str:
    n = sum(1 for r in results[:-1] if r.status in ("recorded", "review"))
    if n == 0:
        return ""
    return f"（另同步 {n} 条）" if lang == "zh" else f" (+{n} synced)"


def _process(cfg: Config, llm: LLMClient, token: str | None, batch: VoiceBatch | None):
    """Runs in a worker thread: own DB connection per request."""
    conn = db.connect(cfg.db_path)
    try:
        expected = repo.get_setting(conn, repo.TOKEN_KEY)
        if not token or not expected or not secrets.compare_digest(
                token.encode(), expected.encode()):
            return None
        if batch is None:
            return []
        lang = repo.get_setting(conn, "lang", "en") or "en"
        results = handle_voice_batch(conn, llm, batch.items, lang)
        return results, lang
    finally:
        conn.close()


def create_voice_app(cfg: Config, llm: LLMClient) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        # Any unknown path/method (incl. GET /api/voice) looks like nothing is there.
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    def unauthorized():
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    @app.post("/api/voice")
    async def voice(request: Request):
        token = _bearer(request.headers.get("authorization"))
        # Authenticate before touching the body.
        if await run_in_threadpool(_process, cfg, llm, token, None) is None:
            return unauthorized()
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_BODY:
            return JSONResponse({"detail": "Payload too large"}, status_code=413)
        body = bytearray()
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_BODY:
                return JSONResponse({"detail": "Payload too large"}, status_code=413)
        try:
            batch = VoiceBatch.model_validate_json(bytes(body))
        except ValidationError:
            return JSONResponse({"detail": "Invalid request"}, status_code=422)
        out = await run_in_threadpool(_process, cfg, llm, token, batch)
        if out is None:  # token rotated mid-request
            return unauthorized()
        results, lang = out
        say = results[-1].say + _suffix(results, lang)
        return {"results": [r.model_dump() for r in results], "say": say}

    return app
