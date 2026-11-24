import sqlite3
from dataclasses import dataclass, fields
from datetime import date

from tally import categories


class DuplicateClientId(Exception):
    pass


@dataclass
class Entry:
    id: int | None
    source: str
    shop: str | None
    date: date | None
    amount_cents: int
    category: str | None
    status: str = "ok"
    reason: str | None = None
    payment_method: str | None = None
    image_path: str | None = None
    ocr_text: str | None = None
    utterance: str | None = None
    client_id: str | None = None
    place_id: int | None = None
    created_at: str | None = None


@dataclass
class Filters:
    start: date
    end: date
    category: str | None = None
    shop: str | None = None
    statuses: tuple[str, ...] = ("ok", "needs_review")


_COLS = [f.name for f in fields(Entry)]
_WRITE_COLS = [c for c in _COLS if c not in ("id", "created_at")]


def _iso(v):
    return v.isoformat() if isinstance(v, date) else v


def _row_to_entry(r: sqlite3.Row) -> Entry:
    d = {c: r[c] for c in _COLS}
    d["date"] = date.fromisoformat(d["date"]) if d["date"] else None
    return Entry(**d)


def _check_category(conn, cat):
    if cat is not None and not categories.is_valid(cat, conn):
        raise ValueError(f"invalid category: {cat!r}")


def add_entry(conn, e: Entry) -> int:
    _check_category(conn, e.category)
    vals = [_iso(getattr(e, c)) for c in _WRITE_COLS]
    sql = (f"INSERT INTO entries({', '.join(_WRITE_COLS)}) "
           f"VALUES ({', '.join('?' * len(_WRITE_COLS))})")
    try:
        cur = conn.execute(sql, vals)
    except sqlite3.IntegrityError as ex:
        if "client_id" in str(ex):
            raise DuplicateClientId(e.client_id) from ex
        raise
    conn.commit()
    return cur.lastrowid


def update_entry(conn, id: int, **fields_) -> None:
    if not fields_:
        return
    bad = set(fields_) - set(_WRITE_COLS)
    if bad:
        raise ValueError(f"unknown entry fields: {sorted(bad)}")
    if "category" in fields_:
        _check_category(conn, fields_["category"])
    sets = ", ".join(f"{k} = ?" for k in fields_)
    conn.execute(f"UPDATE entries SET {sets} WHERE id = ?",
                 [_iso(v) for v in fields_.values()] + [id])
    conn.commit()


def get_entry(conn, id: int) -> Entry | None:
    r = conn.execute("SELECT * FROM entries WHERE id = ?", (id,)).fetchone()
    return _row_to_entry(r) if r else None


def list_entries(conn, f: Filters) -> list[Entry]:
    sql = "SELECT * FROM entries WHERE date >= ? AND date <= ?"
    args: list = [f.start.isoformat(), f.end.isoformat()]
    if f.category is not None:
        sql += " AND category = ?"
        args.append(f.category)
    if f.shop is not None:
        sql += " AND shop = ?"
        args.append(f.shop)
    if f.statuses:
        sql += f" AND status IN ({', '.join('?' * len(f.statuses))})"
        args.extend(f.statuses)
    else:
        sql += " AND 0"
    sql += " ORDER BY date DESC, id DESC"
    return [_row_to_entry(r) for r in conn.execute(sql, args)]


def find_duplicate(conn, shop: str, d: date, cents: int) -> Entry | None:
    r = conn.execute(
        "SELECT * FROM entries WHERE shop = ? AND date = ? AND amount_cents = ? "
        "AND status IN ('ok', 'needs_review') ORDER BY id LIMIT 1",
        (shop, d.isoformat(), cents)).fetchone()
    return _row_to_entry(r) if r else None


def add_withdrawal(conn, d: date, cents: int) -> int:
    cur = conn.execute("INSERT INTO withdrawals(date, amount_cents) VALUES (?, ?)",
                       (d.isoformat(), cents))
    conn.commit()
    return cur.lastrowid


def sum_withdrawals(conn, start: date, end: date) -> int:
    r = conn.execute("SELECT COALESCE(SUM(amount_cents), 0) FROM withdrawals "
                     "WHERE date >= ? AND date <= ?",
                     (start.isoformat(), end.isoformat())).fetchone()
    return r[0]


def remember_shop_category(conn, shop: str, category: str) -> None:
    conn.execute(
        "INSERT INTO shops(name, category, confirmed) VALUES (?, ?, 1) "
        "ON CONFLICT(name) DO UPDATE SET category = excluded.category, confirmed = 1",
        (shop, category))
    conn.commit()


def confirmed_category(conn, shop: str) -> str | None:
    r = conn.execute("SELECT category FROM shops WHERE name = ? AND confirmed = 1",
                     (shop,)).fetchone()
    return r[0] if r else None


def get_setting(conn, key: str, default: str | None = None) -> str | None:
    r = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return r[0] if r else default


def set_setting(conn, key: str, value: str) -> None:
    conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    conn.commit()


def is_processed(conn, h: str) -> bool:
    return conn.execute("SELECT 1 FROM processed_files WHERE hash = ?", (h,)).fetchone() is not None


def mark_processed(conn, h: str, name: str) -> None:
    conn.execute("INSERT OR IGNORE INTO processed_files(hash, original_name) VALUES (?, ?)",
                 (h, name))
    conn.commit()


def count_by_status(conn, status: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM entries WHERE status = ?", (status,)).fetchone()[0]
