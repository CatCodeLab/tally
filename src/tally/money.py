import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

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


def to_cents(amount: Decimal | None) -> int | None:
    """Dollars to cents (ROUND_HALF_UP); None for missing, non-finite or non-positive."""
    if amount is None or not amount.is_finite() or amount <= 0:
        return None
    return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))
