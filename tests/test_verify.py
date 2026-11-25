from datetime import date

from tally.verify import amount_in_text, cash_paid, sane_date

# The bottom of the real Costco receipt that was mis-read as $340.00 (TOTAL lost its number).
COSTCO_TAIL = """SUBTOTAL 309.90
TAX 12.46
米米** TOTAL
CASH 340.00
Penng roundina 0.01
CHANGE 17.65
A 7.650% TAX 5.21
TOTAL TAX 12.46
INSTANT SAVINGS $ 10.50"""


def test_cash_paid_is_cash_minus_change():
    assert cash_paid(COSTCO_TAIL) == 32235
    assert cash_paid("TOTAL 12.50\nCASH TEND 20.00\nCHANGE DUE 7.50") == 1250
    assert cash_paid("TOTAL $12.50\nCASH $20.00\nCHANGE $7.50") == 1250
    assert cash_paid("合计 38.00\n现金 50.00\n找零 12.00") == 3800
    assert cash_paid("实收 100.00\n找零: 1.50") == 9850


def test_cash_paid_amount_on_next_line():
    # OCR sometimes splits the label and its amount onto separate lines.
    assert cash_paid("CASH\n20.00\nCHANGE\n7.50") == 1250


def test_cash_paid_needs_both_lines_and_sane_values():
    assert cash_paid("TOTAL 12.50\nCASH 12.50") is None          # no change line
    assert cash_paid("TOTAL 12.50\nCHANGE 7.50") is None          # no cash line
    assert cash_paid("CASH 5.00\nCHANGE 7.50") is None            # change > cash
    assert cash_paid("CASH 20.00\nCHANGE 20.00") is None          # nothing paid
    assert cash_paid("VISA ****1234 52.10\nCASH BACK 20.00\nCHANGE 0.00") is None
    assert cash_paid("CASHBACK 20.00\nCHANGE 0.00") is None
    assert cash_paid("") is None


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
