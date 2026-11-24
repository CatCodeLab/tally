import json
import re
import sqlite3

CATEGORIES = ["food", "groceries", "clothes", "transport", "household",
              "entertainment", "health", "other"]

_LABELS = {
    "food": ("Food", "餐饮"),
    "groceries": ("Groceries", "买菜日用"),
    "clothes": ("Clothes", "服装"),
    "transport": ("Transport", "交通"),
    "household": ("Household", "家居"),
    "entertainment": ("Entertainment", "娱乐"),
    "health": ("Health", "医疗健康"),
    "other": ("Other", "其他"),
}
_SLUG = re.compile(r"^[a-z][a-z0-9_]{1,20}$")
_KEY = "custom_categories"


def _custom(conn: sqlite3.Connection | None) -> list[dict]:
    if conn is None:
        return []
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (_KEY,)).fetchone()
    return json.loads(row[0]) if row and row[0] else []


def all_slugs(conn: sqlite3.Connection | None = None) -> list[str]:
    return CATEGORIES + [c["slug"] for c in _custom(conn)]


def is_valid(slug: str, conn: sqlite3.Connection | None = None) -> bool:
    return slug in all_slugs(conn)


def normalize(raw: str | None, conn: sqlite3.Connection | None = None) -> str:
    """Valid slug for a model-supplied category, else 'other'."""
    s = (raw or "").strip().lower()
    return s if is_valid(s, conn) else "other"


def label(slug: str, lang: str, conn: sqlite3.Connection | None = None) -> str:
    idx = 1 if lang == "zh" else 0
    if slug in _LABELS:
        return _LABELS[slug][idx]
    for c in _custom(conn):
        if c["slug"] == slug:
            return c["zh" if lang == "zh" else "en"]
    return slug


def add_custom(conn: sqlite3.Connection, slug: str, en: str, zh: str) -> None:
    if not _SLUG.match(slug):
        raise ValueError(f"invalid category slug: {slug!r}")
    if slug in all_slugs(conn):
        raise ValueError(f"category already exists: {slug!r}")
    items = _custom(conn) + [{"slug": slug, "en": en, "zh": zh}]
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_KEY, json.dumps(items, ensure_ascii=False)),
    )
    conn.commit()
