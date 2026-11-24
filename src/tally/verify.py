import re
from datetime import date, timedelta
from decimal import Decimal

_NUM = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+\.\d{2}|\d+")
_MIN_DATE = date(2000, 1, 1)


def amount_in_text(cents: int, text: str) -> bool:
    """True if any number in text equals cents (whole numbers count as dollars)."""
    for m in _NUM.findall(text):
        if int((Decimal(m.replace(",", "")) * 100).to_integral_value()) == cents:
            return True
    return False


def sane_date(d: date | None, ref: date) -> date | None:
    if d is None or d > ref + timedelta(days=1) or d < _MIN_DATE:
        return None
    return d
