from datetime import date

from helpers import mk
from tally.repo import Filters, add_entry, add_withdrawal
from tally.report import summary


def test_summary_totals(conn):
    add_withdrawal(conn, date(2026,11,2), 200000)
    add_entry(conn, mk(date=date(2026,11,3), amount_cents=1250, category="food", shop="McDonald's"))
    add_entry(conn, mk(date=date(2026,11,4), amount_cents=4000, category="groceries", shop="菜市场", status="needs_review"))
    add_entry(conn, mk(date=date(2026,11,5), amount_cents=9999, status="suspected_duplicate"))
    s = summary(conn, Filters(date(2026,11,1), date(2026,11,30)))
    assert (s.withdrawn_cents, s.recorded_cents, s.unconfirmed_cents) == (200000, 5250, 4000)
    assert s.unaccounted_cents == 200000 - 5250
    assert s.by_category == [("groceries", 4000), ("food", 1250)]
    assert s.review_count == 2


def test_negative_unaccounted(conn):
    add_entry(conn, mk(date=date(2026,11,3), amount_cents=5000))
    assert summary(conn, Filters(date(2026,11,1), date(2026,11,30))).unaccounted_cents == -5000


def test_weekly_buckets_include_zeros(conn):
    s = summary(conn, Filters(date(2026,11,1), date(2026,11,30)))
    assert [b[0] for b in s.buckets] == ["2026-10-26","2026-11-02","2026-11-09","2026-11-16","2026-11-23","2026-11-30"]


def test_bucket_amounts_and_monthly(conn):
    add_entry(conn, mk(date=date(2026,11,3), amount_cents=100))
    add_entry(conn, mk(date=date(2026,11,8), amount_cents=50))
    s = summary(conn, Filters(date(2026,11,1), date(2026,11,10)))
    assert dict(s.buckets)["2026-11-02"] == 150
    add_entry(conn, mk(date=date(2026,9,15), amount_cents=70))
    s = summary(conn, Filters(date(2026,8,1), date(2026,11,30)))
    assert s.buckets == [("2026-08",0),("2026-09",70),("2026-10",0),("2026-11",150)]


def test_withdrawn_ignores_category_shop_and_review_count_ignores_range(conn):
    add_withdrawal(conn, date(2026,11,2), 1000)
    add_entry(conn, mk(date=date(2025,1,1), status="needs_review"))
    add_entry(conn, mk(date=date(2026,11,3), amount_cents=300, category="food", shop="A"))
    s = summary(conn, Filters(date(2026,11,1), date(2026,11,30), category="food", shop="A"))
    assert s.withdrawn_cents == 1000 and s.recorded_cents == 300
    assert s.review_count == 1


def test_top_shops_limit_and_order(conn):
    for i in range(12):
        add_entry(conn, mk(shop=f"s{i}", amount_cents=100 + i))
    add_entry(conn, mk(shop="s11", amount_cents=1))
    s = summary(conn, Filters(date(2026,11,1), date(2026,11,30)))
    assert len(s.top_shops) == 10
    assert s.top_shops[0] == ("s11", 112, 2)
    assert s.top_shops[1] == ("s10", 110, 1)
