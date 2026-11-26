import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop TEXT NULL,
    lat REAL,
    lon REAL,
    visits INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,          -- receipt | voice | manual
    shop TEXT,
    date TEXT,                     -- ISO
    amount_cents INTEGER NOT NULL DEFAULT 0,
    category TEXT,
    status TEXT NOT NULL DEFAULT 'ok',  -- ok | needs_review | suspected_duplicate | card_skipped | deleted
    reason TEXT NULL,
    payment_method TEXT,
    image_path TEXT,
    ocr_text TEXT,
    utterance TEXT,
    client_id TEXT UNIQUE,
    place_id INTEGER REFERENCES places(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    amount_cents INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS shops (
    name TEXT PRIMARY KEY,
    category TEXT,
    confirmed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS processed_files (
    hash TEXT PRIMARY KEY,
    original_name TEXT,
    processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(path: Path) -> sqlite3.Connection:
    # WAL lets the dashboard read while a scan writes; timeout waits out short write locks.
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
