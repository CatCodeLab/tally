import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

Preset = Literal["this_month", "last_month", "last_3_months", "this_year"]


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def _month_range(year: int, month: int) -> DateRange:
    return DateRange(date(year, month, 1),
                     date(year, month, calendar.monthrange(year, month)[1]))


def _add_months(year: int, month: int, n: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + n
    return idx // 12, idx % 12 + 1


def preset(name: Preset, today: date) -> DateRange:
    if name == "this_month":
        return _month_range(today.year, today.month)
    if name == "last_month":
        return _month_range(*_add_months(today.year, today.month, -1))
    if name == "last_3_months":
        y, m = _add_months(today.year, today.month, -2)
        return DateRange(date(y, m, 1), today)
    if name == "this_year":
        return DateRange(date(today.year, 1, 1), today)
    raise ValueError(f"unknown preset: {name!r}")


def shift(r: DateRange, direction: int) -> DateRange:
    if r == _month_range(r.start.year, r.start.month):
        return _month_range(*_add_months(r.start.year, r.start.month, direction))
    delta = timedelta(days=r.days * direction)
    return DateRange(r.start + delta, r.end + delta)


def granularity(r: DateRange) -> Literal["week", "month"]:
    return "week" if r.days <= 62 else "month"
