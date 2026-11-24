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
