import pytest

from tally.money import format_cents, parse_amount


def test_parse_amount():
    assert parse_amount("$1,234.56") == 123456
    assert parse_amount("12.5") == 1250
    assert parse_amount("40") == 4000
    with pytest.raises(ValueError):
        parse_amount("abc")


def test_format_cents():
    assert format_cents(123456) == "$1,234.56"
    assert format_cents(-1250) == "−$12.50"
