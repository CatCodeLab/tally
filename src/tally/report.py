from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

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
    filtered: bool = False  # category/shop filter applied (withdrawn/unaccounted ignore it)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _bucket_keys(r: DateRange, gran: Literal["week", "month"]) -> list[str]:
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


def _bucket_key(d: date, gran: Literal["week", "month"]) -> str:
    return _monday(d).isoformat() if gran == "week" else f"{d.year:04d}-{d.month:02d}"


def summary(conn, f: Filters) -> Summary:
    entries = repo.list_entries(conn, f)
    withdrawn = repo.sum_withdrawals(conn, f.start, f.end)
    recorded = sum(e.amount_cents for e in entries)
    filtered = f.category is not None or f.shop is not None
    # Cash withdrawn has no category or shop, so the gap is always over everything in range.
    recorded_all = (sum(e.amount_cents for e in repo.list_entries(
        conn, Filters(f.start, f.end, statuses=f.statuses))) if filtered else recorded)
    unconfirmed = sum(e.amount_cents for e in entries if e.status == "needs_review")

    cats: dict[str, int] = defaultdict(int)
    shops: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    rng = DateRange(f.start, f.end)
    gran = granularity(rng)
    buckets = dict.fromkeys(_bucket_keys(rng, gran), 0)
    for e in entries:
        cats[e.category or "other"] += e.amount_cents
        if e.shop:
            shops[e.shop][0] += e.amount_cents
            shops[e.shop][1] += 1
        buckets[_bucket_key(e.date, gran)] += e.amount_cents

    by_category = sorted(((c, v) for c, v in cats.items() if v), key=lambda x: -x[1])
    top_shops = sorted(((s, v[0], v[1]) for s, v in shops.items()), key=lambda x: -x[1])[:10]
    review_count = (repo.count_by_status(conn, "needs_review")
                    + repo.count_by_status(conn, "suspected_duplicate"))
    return Summary(withdrawn, recorded, withdrawn - recorded_all, unconfirmed,
                   by_category, list(buckets.items()), top_shops, review_count, filtered)
