def test_schema_tables(conn):
    names = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    assert {"entries", "withdrawals", "shops", "places", "settings", "processed_files"} <= names


def test_entry_columns(conn):
    cols = {r[1] for r in conn.execute("pragma table_info(entries)")}
    assert {"id", "source", "shop", "date", "amount_cents", "category", "status", "reason",
            "payment_method", "image_path", "ocr_text", "utterance", "client_id", "place_id",
            "created_at"} <= cols
    assert "lat" not in cols and "lon" not in cols  # spec §5.7.2


def test_foreign_keys_and_row_factory(conn):
    assert conn.execute("pragma foreign_keys").fetchone()[0] == 1
    conn.execute("insert into settings(key, value) values ('a', 'b')")
    assert conn.execute("select * from settings").fetchone()["value"] == "b"


def test_client_id_unique(conn):
    import sqlite3

    import pytest
    conn.execute("insert into entries(source, client_id) values ('voice', 'x')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("insert into entries(source, client_id) values ('voice', 'x')")


def test_config(tmp_config, tmp_path):
    assert tmp_config.home == tmp_path
    assert tmp_config.inbox == tmp_path / "inbox" and tmp_config.inbox.is_dir()
    assert tmp_config.archive.is_dir()
    assert tmp_config.db_path == tmp_path / "tally.db"
    assert tmp_config.model == "qwen2.5:7b"
    assert (tmp_config.dash_port, tmp_config.voice_port) == (8765, 8766)


def test_wal_and_busy_timeout(tmp_config, monkeypatch):
    import sqlite3

    from tally import db
    seen = {}
    real = sqlite3.connect

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)
    monkeypatch.setattr(db.sqlite3, "connect", spy)
    c = db.connect(tmp_config.db_path)
    try:
        assert c.execute("pragma journal_mode").fetchone()[0] == "wal"
        assert seen.get("timeout") == 15
    finally:
        c.close()
