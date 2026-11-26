import json

import pytest

from tally import db
from tally.config import Config


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    for k in ("TALLY_INBOX", "TALLY_MODEL", "TALLY_OLLAMA_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TALLY_HOME", str(tmp_path))
    return Config.from_env()


@pytest.fixture
def conn(tmp_config):
    c = db.connect(tmp_config.db_path)
    yield c
    c.close()


class MockOllama:
    def __init__(self):
        import httpx

        from tally.llm import OllamaClient

        self.last_request = None
        self._body = {}
        self._raw = None

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}]})
            self.last_request = json.loads(request.content)
            if self._raw is not None:
                return httpx.Response(200, content=self._raw)
            return httpx.Response(200, json=self._body)

        self.client = OllamaClient("http://127.0.0.1:11434", "qwen2.5:7b",
                                   transport=httpx.MockTransport(handler))

    def reply(self, fields: dict):
        self._raw = None
        self._body = {"message": {"role": "assistant", "content": json.dumps(fields)}}

    def reply_raw(self, content: str):
        self._raw = None
        self._body = {"message": {"role": "assistant", "content": content}}

    def reply_body(self, raw: str):
        """Reply with a raw HTTP body (to test malformed envelopes)."""
        self._raw = raw.encode()


@pytest.fixture
def mock_ollama():
    return MockOllama()
