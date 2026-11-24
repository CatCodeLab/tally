from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from tally import repo
from tally.dates import DateRange, granularity
from tally.repo import Filters


@dataclass
class Summary:
    withdrawn_cents: int
    recorded_cents: int
    unaccounted_cents: int
    unconfirmed_cents: int
    by_category: list[tuple[str, int]]
    buckets: list[tuple[str, int]]
    top_shops: list[tuple[str, int, int]]
    review_count: int


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _bucket_keys(r: DateRange, gran: str) -> list[str]:
    keys: list[str] = []
    if gran == "week":
        d = _monday(r.start)
        while d <= r.end:
            keys.append(d.isoformat())
            d += timedelta(days=7)
    else:
        y, m = r.start.year, r.start.month
        while (y, m) <= (r.end.year, r.end.month):
            keys.append(f"{y:04d}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return keys


def _bucket_key(d: date, gran: str) -> str:
    return _monday(d).isoformat() if gran == "week" else f"{d.year:04d}-{d.month:02d}"


def summary(conn, f: Filters) -> Summary:
    entries = repo.list_entries(conn, f)
    withdrawn = repo.sum_withdrawals(conn, f.start, f.end)
    recorded = sum(e.amount_cents for e in entries)
    unconfirmed = sum(e.amount_cents for e in entries if e.status == "needs_review")

    cats: dict[str, int] = defaultdict(int)
    shops: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    gran = granularity(DateRange(f.start, f.end))
    buckets = dict.fromkeys(_bucket_keys(DateRange(f.start, f.end), gran), 0)
    for e in entries:
        cats[e.category or "uncategorized"] += e.amount_cents
        if e.shop:
            shops[e.shop][0] += e.amount_cents
            shops[e.shop][1] += 1
        buckets[_bucket_key(e.date, gran)] += e.amount_cents

    by_category = sorted(((c, v) for c, v in cats.items() if v), key=lambda x: -x[1])
    top_shops = sorted(((s, v[0], v[1]) for s, v in shops.items()), key=lambda x: -x[1])[:10]
    review_count = (repo.count_by_status(conn, "needs_review")
                    + repo.count_by_status(conn, "suspected_duplicate"))
    return Summary(withdrawn, recorded, withdrawn - recorded, unconfirmed,
                   by_category, list(buckets.items()), top_shops, review_count)
