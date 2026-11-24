from datetime import date

from tally.repo import Entry


def mk(**kw):
    base = dict(id=None, source="manual", shop="S", date=date(2026, 11, 1),
                amount_cents=100, category="other", status="ok")
    base.update(kw)
    return Entry(**base)


from datetime import datetime, timezone  # noqa: E402

from tally import repo  # noqa: E402
from tally.places import add_place  # noqa: E402,F401
from tally.voice import VoiceItem  # noqa: E402


def dt(y, m, d):
    return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)


def item(text, id="u1", captured_at=None, lat=None, lon=None):
    return VoiceItem(id=id, text=text, captured_at=captured_at or dt(2026, 11, 24),
                     lat=lat, lon=lon)


class NoLLM:
    def health(self):
        pass

    def parse_utterance(self, text, captured, categories=None):
        raise AssertionError("LLM must not be called")


class FakeLLM:
    def __init__(self, utterances):
        self.queue = list(utterances)
        self.calls = []

    def health(self):
        pass

    def parse_utterance(self, text, captured, categories=None):
        self.calls.append(type("Call", (), {"text": text, "captured": captured,
                                            "categories": categories})())
        r = self.queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def by_client_id(conn, cid):
    r = conn.execute("SELECT id FROM entries WHERE client_id = ?", (cid,)).fetchone()
    return repo.get_entry(conn, r[0])


def count_entries(conn):
    return conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
