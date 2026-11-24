from datetime import date

from tally.dates import DateRange, granularity, preset, shift


def test_presets():
    t = date(2026,11,24)
    assert preset("this_month", t) == DateRange(date(2026,11,1), date(2026,11,30))
    assert preset("last_month", t) == DateRange(date(2026,10,1), date(2026,10,31))
    assert preset("last_3_months", t) == DateRange(date(2026,9,1), t)
    assert preset("this_year", t) == DateRange(date(2026,1,1), t)


def test_presets_year_boundary():
    t = date(2026,1,15)
    assert preset("last_month", t) == DateRange(date(2025,12,1), date(2025,12,31))
    assert preset("last_3_months", t) == DateRange(date(2025,11,1), t)


def test_days_inclusive():
    assert DateRange(date(2026,11,1), date(2026,11,1)).days == 1


def test_shift():
    assert shift(DateRange(date(2026,11,1), date(2026,11,30)), -1) == DateRange(date(2026,10,1), date(2026,10,31))
    assert shift(DateRange(date(2026,11,1), date(2026,11,10)), 1) == DateRange(date(2026,11,11), date(2026,11,20))


def test_shift_month_across_year_and_lengths():
    assert shift(DateRange(date(2026,1,1), date(2026,1,31)), -1) == DateRange(date(2025,12,1), date(2025,12,31))
    assert shift(DateRange(date(2026,1,1), date(2026,1,31)), 1) == DateRange(date(2026,2,1), date(2026,2,28))


def test_granularity():
    assert granularity(DateRange(date(2026,9,24), date(2026,11,24))) == "week"     # 62 days
    assert granularity(DateRange(date(2026,9,1), date(2026,11,24))) == "month"
