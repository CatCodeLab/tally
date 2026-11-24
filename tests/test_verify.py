from datetime import date

from tally.verify import amount_in_text, sane_date


def test_amount_in_text():
    assert amount_in_text(1250, "SUBTOTAL 11.40\nTOTAL $12.50\nCASH 20.00")
    assert amount_in_text(123456, "合计 1,234.56")
    assert not amount_in_text(1250, "TOTAL 15.20")


def test_whole_numbers_are_dollars():
    assert amount_in_text(1200, "TOTAL ¥12")
    assert not amount_in_text(12, "TOTAL 12")


def test_rejects_future_date():
    ref = date(2026, 11, 24)
    assert sane_date(date(2062, 11, 24), ref) is None
    assert sane_date(date(1999, 12, 31), ref) is None
    assert sane_date(date(2026, 11, 25), ref) == date(2026, 11, 25)
    assert sane_date(date(2026, 11, 26), ref) is None
    assert sane_date(None, ref) is None
