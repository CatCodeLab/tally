from datetime import date

import pytest

from helpers import mk

from tally.repo import (DuplicateClientId, Entry, Filters, add_entry, add_withdrawal,
                        confirmed_category, count_by_status, find_duplicate, get_entry,
                        get_setting, is_processed, list_entries, mark_processed,
                        remember_shop_category, set_setting, sum_withdrawals, update_entry)


def test_add_and_filter(conn):
    add_entry(conn, mk(shop="McDonald's", date=date(2026,11,3), amount_cents=1250, category="food"))
    add_entry(conn, mk(shop="UNIQLO", date=date(2026,11,18), amount_cents=23000, category="clothes"))
    add_entry(conn, mk(shop="X", date=date(2026,11,5), amount_cents=999, status="card_skipped"))
    got = list_entries(conn, Filters(date(2026,11,1), date(2026,11,30)))
    assert [e.shop for e in got] == ["UNIQLO", "McDonald's"]
    assert [e.shop for e in list_entries(conn, Filters(date(2026,11,1), date(2026,11,30), category="food"))] == ["McDonald's"]
    assert [e.shop for e in list_entries(conn, Filters(date(2026,11,3), date(2026,11,3), shop="McDonald's"))] == ["McDonald's"]


def test_client_id_unique(conn):
    add_entry(conn, mk(client_id="abc"))
    with pytest.raises(DuplicateClientId):
        add_entry(conn, mk(client_id="abc"))


def test_shop_category_memory(conn):
    assert confirmed_category(conn, "菜市场") is None
    remember_shop_category(conn, "菜市场", "groceries")
    assert confirmed_category(conn, "菜市场") == "groceries"


def test_find_duplicate_ignores_deleted(conn):
    add_entry(conn, mk(shop="A", date=date(2026,11,1), amount_cents=500, status="deleted"))
    assert find_duplicate(conn, "A", date(2026,11,1), 500) is None
    add_entry(conn, mk(shop="A", date=date(2026,11,1), amount_cents=500, status="needs_review"))
    assert find_duplicate(conn, "A", date(2026,11,1), 500).status == "needs_review"


def test_get_update_roundtrip(conn):
    i = add_entry(conn, mk(shop="A"))
    assert get_entry(conn, i).date == date(2026, 11, 1)
    update_entry(conn, i, status="deleted", date=date(2026, 12, 2))
    e = get_entry(conn, i)
    assert e.status == "deleted" and e.date == date(2026, 12, 2)
    assert get_entry(conn, 999) is None
    with pytest.raises(ValueError):
        update_entry(conn, i, bogus=1)
    with pytest.raises(ValueError):
        update_entry(conn, i, category="nope")


def test_withdrawals_settings_processed_counts(conn):
    add_withdrawal(conn, date(2026,11,1), 5000)
    add_withdrawal(conn, date(2026,11,30), 1000)
    add_withdrawal(conn, date(2026,12,1), 700)
    assert sum_withdrawals(conn, date(2026,11,1), date(2026,11,30)) == 6000
    assert get_setting(conn, "k") is None and get_setting(conn, "k", "d") == "d"
    set_setting(conn, "k", "1"); set_setting(conn, "k", "2")
    assert get_setting(conn, "k") == "2"
    assert not is_processed(conn, "h")
    mark_processed(conn, "h", "a.jpg")
    assert is_processed(conn, "h")
    add_entry(conn, mk(status="needs_review"))
    assert count_by_status(conn, "needs_review") == 1


def test_list_and_delete_withdrawals(conn):
    from tally.repo import Withdrawal, add_withdrawal, delete_withdrawal, list_withdrawals
    a = add_withdrawal(conn, date(2026, 11, 2), 5000)
    b = add_withdrawal(conn, date(2026, 11, 9), 2000)
    add_withdrawal(conn, date(2026, 10, 9), 999)
    got = list_withdrawals(conn, date(2026, 11, 1), date(2026, 11, 30))
    assert got == [Withdrawal(b, date(2026, 11, 9), 2000), Withdrawal(a, date(2026, 11, 2), 5000)]
    delete_withdrawal(conn, a)
    assert [w.id for w in list_withdrawals(conn, date(2026, 11, 1), date(2026, 11, 30))] == [b]
