import re
from datetime import date, timedelta
from decimal import Decimal

_NUM = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+\.\d{2}|\d+")
_MIN_DATE = date(2000, 1, 1)

_MONEY = re.compile(r"\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2}")
_ONLY_MONEY = re.compile(r"\s*\$?\s*(\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2})\s*")
# "CASH", "CASH TEND", "TENDERED", 现金, 实收 -- but never "CASH BACK" / "CASHBACK".
_CASH = re.compile(r"\bCASH\b(?!\s*BACK)|\bTENDERED\b|现金|实收", re.IGNORECASE)
_CHANGE = re.compile(r"\bCHANGE\b|找零|找赎|找续", re.IGNORECASE)


def _cents(s: str) -> int:
    return int((Decimal(s.replace(",", "")) * 100).to_integral_value())


def amount_in_text(cents: int, text: str) -> bool:
    """True if any number in text equals cents (whole numbers count as dollars)."""
    return any(_cents(m) == cents for m in _NUM.findall(text))


def _labelled_amount(lines: list[str], label: re.Pattern) -> int | None:
    """Amount on the first line matching label, or on the next line if it holds only an amount."""
    for i, line in enumerate(lines):
        if not label.search(line):
            continue
        found = _MONEY.findall(line)
        if found:
            return _cents(found[-1])
        if i + 1 < len(lines) and (m := _ONLY_MONEY.fullmatch(lines[i + 1])):
            return _cents(m.group(1))
        return None
    return None


def cash_and_change(text: str) -> tuple[int, int] | None:
    """(cash tendered, change) in cents, when both lines are present and cash > change."""
    lines = text.splitlines()
    cash, change = _labelled_amount(lines, _CASH), _labelled_amount(lines, _CHANGE)
    if cash is None or change is None or cash <= change:
        return None
    return cash, change


def cash_paid(text: str) -> int | None:
    """Cash actually spent, in cents: the CASH (tendered) line minus the CHANGE line."""
    cc = cash_and_change(text)
    return cc[0] - cc[1] if cc else None


def sane_date(d: date | None, ref: date) -> date | None:
    if d is None or d > ref + timedelta(days=1) or d < _MIN_DATE:
        return None
    return d
