import re
from decimal import Decimal, InvalidOperation

_AMOUNT = re.compile(r"^\$?\d{1,3}(,\d{3})+(\.\d+)?$|^\$?\d+(\.\d+)?$")


def parse_amount(s: str) -> int:
    """Parse '12.5', '$1,234.56', '40' into integer cents."""
    text = s.strip()
    if not _AMOUNT.match(text):
        raise ValueError(f"invalid amount: {s!r}")
    try:
        d = Decimal(text.replace("$", "").replace(",", ""))
    except InvalidOperation:
        raise ValueError(f"invalid amount: {s!r}") from None
    return int((d * 100).to_integral_value())


def format_cents(c: int) -> str:
    sign = "−" if c < 0 else ""
    return f"{sign}${abs(c) / 100:,.2f}"
