from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tally.llm import ExtractionError, UtteranceFields
from tally.repo import name_entry_shop, remember_shop_category
from tally.voice import handle_voice_batch
from helpers import (FakeLLM, NoLLM, add_place, by_client_id, count_entries,
                           dt, item)


def test_amount_only_known_place(conn):
    add_place(conn, "菜市场", 40.7128, -74.0060, visits=3)
    remember_shop_category(conn, "菜市场", "groceries")
    [r] = handle_voice_batch(conn, NoLLM(), [item("40", lat=40.71282, lon=-74.00601)], "zh")
    e = by_client_id(conn, r.id)
    assert (e.shop, e.amount_cents, e.category, e.status) == ("菜市场", 4000, "groceries", "ok")
    assert r.say == "已记录：菜市场 $40.00，买菜日用"
    assert r.status == "recorded"


def test_unknown_place_then_named_learns(conn):
    [r] = handle_voice_batch(conn, NoLLM(), [item("40", lat=1.0, lon=1.0)], "en")
    e = by_client_id(conn, r.id)
    assert e.reason == "unknown_place" and r.status == "review"
    assert r.say == "Recorded: Unknown shop $40.00, Other — please check"
    name_entry_shop(conn, e.id, "Corner Deli")
    [r2] = handle_voice_batch(conn, NoLLM(), [item("12", id="u2", lat=1.0, lon=1.0)], "en")
    assert by_client_id(conn, r2.id).shop == "Corner Deli"


def test_relative_date_uses_capture_time(conn):
    llm = FakeLLM([UtteranceFields(shop="McDonald's", amount=Decimal("12.5"),
                                   date=date(2026, 11, 20), category="food")])
    [r] = handle_voice_batch(conn, llm, [item("McDonald's 12.5 yesterday",
                                              captured_at=dt(2026, 11, 21))], "en")
    assert llm.calls[0].captured == date(2026, 11, 21)
    assert by_client_id(conn, r.id).date == date(2026, 11, 20)
    assert llm.calls[0].categories[0] == "food"


def test_bad_date_and_category_fall_back(conn):
    llm = FakeLLM([UtteranceFields(shop="S", amount=Decimal("3"), date=date(2030, 1, 1),
                                   category="bogus")])
    [r] = handle_voice_batch(conn, llm, [item("S 3")], "en")
    e = by_client_id(conn, r.id)
    assert e.date == date(2026, 11, 24) and e.category == "other"
    assert (e.status, e.reason, r.status) == ("needs_review", "bad_date", "review")
    assert r.say == "Recorded: S $3.00, Other — please check"


def test_unspoken_date_is_not_bad_date(conn):
    llm = FakeLLM([UtteranceFields(shop="S", amount=Decimal("3"), date=None, category=None)])
    [r] = handle_voice_batch(conn, llm, [item("S 3")], "en")
    e = by_client_id(conn, r.id)
    assert (e.date, e.status, e.reason) == (date(2026, 11, 24), "ok", None)


@pytest.mark.parametrize("text,status,reason", [("500", "ok", None), ("500.01", "needs_review",
                                                 "large_amount")])
def test_large_amount_flagged(conn, text, status, reason):
    add_place(conn, "Shop", 3.0, 3.0)
    [r] = handle_voice_batch(conn, NoLLM(), [item(text, lat=3.0, lon=3.0)], "en")
    e = by_client_id(conn, r.id)
    assert (e.shop, e.status, e.reason) == ("Shop", status, reason)


def test_retry_is_duplicate(conn):
    it = item("40", id="u1")
    handle_voice_batch(conn, NoLLM(), [it], "en")
    assert handle_voice_batch(conn, NoLLM(), [it], "en")[0].status == "duplicate"
    assert count_entries(conn) == 1


def test_ambiguous_place(conn):
    add_place(conn, "A", 10.0, 10.0, visits=2)
    add_place(conn, "B", 10.0001, 10.0, visits=5)
    [r] = handle_voice_batch(conn, NoLLM(), [item("9", lat=10.0, lon=10.0)], "en")
    e = by_client_id(conn, r.id)
    assert (e.shop, e.status, e.reason) == ("B", "needs_review", "ambiguous_place")


def test_no_amount_review(conn):
    llm = FakeLLM([UtteranceFields(shop="S", amount=None, date=None, category="food")])
    [r] = handle_voice_batch(conn, llm, [item("went to S")], "en")
    e = by_client_id(conn, r.id)
    assert (e.amount_cents, e.status, e.reason) == (0, "needs_review", "no_amount")


def test_nonpositive_amount_is_missing(conn):
    llm = FakeLLM([UtteranceFields(shop="S", amount=Decimal("-5"), date=None, category=None)])
    [r] = handle_voice_batch(conn, llm, [item("S minus 5")], "en")
    assert by_client_id(conn, r.id).reason == "no_amount"


def test_extraction_failed(conn):
    [r] = handle_voice_batch(conn, FakeLLM([ExtractionError("x")]), [item("blah")], "en")
    e = by_client_id(conn, r.id)
    assert (e.amount_cents, e.reason, e.status) == (0, "extraction_failed", "needs_review")


def test_no_coordinates_stored_on_entry(conn):
    handle_voice_batch(conn, NoLLM(), [item("5", lat=2.0, lon=2.0)], "en")
    cols = [c[1] for c in conn.execute("PRAGMA table_info(entries)")]
    assert "lat" not in cols and "lon" not in cols


@pytest.mark.parametrize("lat,lon", [(91, 0), (-91, 0), (0, 181), (0, -181),
                                     (float("nan"), 0), (0, float("inf"))])
def test_voice_item_rejects_bad_coords(lat, lon):
    with pytest.raises(ValidationError):
        item("1", lat=lat, lon=lon)


def test_correcting_place_filled_shop_teaches_place(conn):
    [r] = handle_voice_batch(conn, NoLLM(), [item("40", lat=5.0, lon=5.0)], "en")
    e = by_client_id(conn, r.id)
    assert e.reason == "unknown_place"
    name_entry_shop(conn, e.id, "Corner Deli")
    [r2] = handle_voice_batch(conn, NoLLM(), [item("12", id="u2", lat=5.0, lon=5.0)], "en")
    e2 = by_client_id(conn, r2.id)
    assert (e2.shop, e2.status) == ("Corner Deli", "ok")
    name_entry_shop(conn, e2.id, "Corner Deli & Co")
    [r3] = handle_voice_batch(conn, NoLLM(), [item("5", id="u3", lat=5.0, lon=5.0)], "en")
    assert by_client_id(conn, r3.id).shop == "Corner Deli & Co"


def test_rename_does_not_steal_place_named_otherwise(conn):
    pid = add_place(conn, "Bakery", 6.0, 6.0)
    conn.execute("INSERT INTO entries(source, shop, date, place_id) "
                 "VALUES ('manual', 'Typo', '2026-11-24', ?)", (pid,))
    eid = conn.execute("SELECT id FROM entries").fetchone()[0]
    name_entry_shop(conn, eid, "Fixed")
    assert conn.execute("SELECT shop FROM places WHERE id = ?", (pid,)).fetchone()[0] == "Bakery"


def test_two_amount_only_at_unnamed_point_reuse_one_place(conn):
    handle_voice_batch(conn, NoLLM(), [item("4", id="a", lat=7.0, lon=7.0),
                                       item("6", id="b", lat=7.0, lon=7.0)], "en")
    rows = conn.execute("SELECT id, shop, visits FROM places").fetchall()
    assert [(r["shop"], r["visits"]) for r in rows] == [(None, 2)]
    assert by_client_id(conn, "a").place_id == by_client_id(conn, "b").place_id == rows[0]["id"]


def test_whitespace_only_text_is_invalid():
    from tally.voice import VoiceResult, validate_item
    r = validate_item({"id": "a", "text": "   ", "captured_at": "2026-11-24T10:00:00Z"})
    assert isinstance(r, VoiceResult) and r.status == "invalid" and r.id == "a"
