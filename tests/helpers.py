from datetime import date

from tally.repo import Entry


def mk(**kw):
    base = dict(id=None, source="manual", shop="S", date=date(2026, 11, 1),
                amount_cents=100, category="other", status="ok")
    base.update(kw)
    return Entry(**base)
