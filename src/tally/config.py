import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    home: Path
    inbox: Path
    archive: Path
    db_path: Path
    model: str
    ollama_url: str
    dash_port: int = 8765
    voice_port: int = 8766

    @classmethod
    def from_env(cls) -> "Config":
        home = Path(os.environ.get("TALLY_HOME") or "~/Tally").expanduser()
        inbox = Path(os.environ.get("TALLY_INBOX") or home / "inbox").expanduser()
        cfg = cls(
            home=home,
            inbox=inbox,
            archive=home / "receipts",
            db_path=home / "tally.db",
            model=os.environ.get("TALLY_MODEL", "qwen2.5:7b"),
            ollama_url=os.environ.get("TALLY_OLLAMA_URL", "http://127.0.0.1:11434"),
        )
        for d in (cfg.home, cfg.inbox, cfg.archive):
            d.mkdir(parents=True, exist_ok=True)
        return cfg
