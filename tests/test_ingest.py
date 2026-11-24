from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from PIL import Image

from tally import db
from tally.ingest import scan_inbox
from tally.llm import ExtractionError, LLMUnavailable, ReceiptFields
from tally.repo import Filters, list_entries, mark_processed, remember_shop_category, add_entry
from helpers import mk

D = date(2026, 11, 24)


def ok_fields(**kw):
    base = dict(shop="McDonald's", date=date(2026, 11, 23), total=Decimal("12.50"),
                category="food", payment_method="cash", confidence=0.9)
    if "total" in kw and isinstance(kw["total"], str):
        kw["total"] = Decimal(kw["total"])
    base.update(kw)
    return ReceiptFields.model_construct(**base)  # bypass validation: NaN/Inf must be handled


class FakeLLM:
    def __init__(self, queue):
        self.queue = list(queue)

    def health(self):
        pass

    def extract_receipt(self, text, categories=None):
        self.categories = categories
        r = self.queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class DownLLM(FakeLLM):
    def health(self):
        raise LLMUnavailable("down")


def put_png(inbox, name="a.png", color=(255, 0, 0)):
    Image.new("RGB", (4, 4), color).save(inbox / name)


@pytest.fixture
def env(tmp_config, conn):
    put_png(tmp_config.inbox)
    return SimpleNamespace(conn=conn, cfg=tmp_config)


def entries(conn):
    return list_entries(conn, Filters(date(2000, 1, 1), date(2100, 1, 1),
                                      statuses=("ok", "needs_review", "suspected_duplicate",
                                                "card_skipped")))


def only_entry(conn):
    es = entries(conn)
    assert len(es) == 1
    return es[0]


def run(env, fields, text="TOTAL 12.50"):
    return scan_inbox(env.conn, env.cfg, FakeLLM(fields), ocr=lambda i: text, today=D)


def test_happy_path(env):
    r = run(env, [ok_fields()])
    assert (r.added, r.review) == (1, 0)
    assert list(env.cfg.inbox.iterdir()) == []
    e = only_entry(env.conn)
    assert (e.status, e.amount_cents, e.source) == ("ok", 1250, "receipt")
    assert e.image_path and e.image_path.endswith("-p0.png")
    assert e.ocr_text == "TOTAL 12.50"


def test_categories_passed_and_invalid_category_falls_back(env):
    llm = FakeLLM([ok_fields(category="Bogus!")])
    scan_inbox(env.conn, env.cfg, llm, ocr=lambda i: "TOTAL 12.50", today=D)
    assert "food" in llm.categories
    assert only_entry(env.conn).category == "other"


def test_blank_receipt_goes_to_review(env):
    r = run(env, [], text="")
    e = only_entry(env.conn)
    assert (e.status, e.reason, e.amount_cents) == ("needs_review", "no_total", 0)
    assert r.review == 1


def test_extraction_failed(env):
    run(env, [ExtractionError("bad")])
    e = only_entry(env.conn)
    assert (e.status, e.reason, e.amount_cents) == ("needs_review", "extraction_failed", 0)


def test_amount_mismatch_flagged(env):
    run(env, [ok_fields(total="99.99")])
    assert only_entry(env.conn).reason == "amount_mismatch"


@pytest.mark.parametrize("total", [None, Decimal("0"), Decimal("-3"), Decimal("NaN"),
                                   Decimal("Infinity")])
def test_bad_totals_are_no_total(env, total):
    run(env, [ok_fields(total=total)])
    e = only_entry(env.conn)
    assert (e.reason, e.amount_cents, e.status) == ("no_total", 0, "needs_review")


def test_half_up_rounding(env):
    run(env, [ok_fields(total=Decimal("0.125"))], text="0.125 13")
    assert only_entry(env.conn).amount_cents == 13


def test_bad_date_falls_back_to_today(env):
    run(env, [ok_fields(date=date(2030, 1, 1))])
    e = only_entry(env.conn)
    assert (e.reason, e.date) == ("bad_date", D)


def test_no_shop_and_low_confidence(env):
    run(env, [ok_fields(shop=None)])
    assert only_entry(env.conn).reason == "no_shop"


def test_low_confidence(env):
    run(env, [ok_fields(confidence=0.5)])
    assert only_entry(env.conn).reason == "low_confidence"


def test_card_receipt_skipped(env):
    r = run(env, [ok_fields(payment_method="card")])
    assert only_entry(env.conn).status == "card_skipped"
    assert r.card == 1 and r.added == 0


def test_confirmed_category_wins(env):
    remember_shop_category(env.conn, "McDonald's", "household")
    run(env, [ok_fields()])
    assert only_entry(env.conn).category == "household"


def test_duplicate_flagged(env):
    add_entry(env.conn, mk(shop="McDonald's", date=date(2026, 11, 23), amount_cents=1250))
    run(env, [ok_fields()])
    new = [e for e in entries(env.conn) if e.source == "receipt"]
    assert new[0].status == "suspected_duplicate"


def test_same_file_twice_is_skipped(env):
    run(env, [ok_fields()])
    put_png(env.cfg.inbox)
    r = run(env, [])
    assert r.skipped_files == 1 and len(entries(env.conn)) == 1
    assert list(env.cfg.inbox.iterdir()) == []


def test_name_clash_in_archive(env):
    run(env, [ok_fields()])
    put_png(env.cfg.inbox, color=(0, 255, 0))
    run(env, [ok_fields(shop="Other")])
    names = sorted(p.name for p in env.cfg.archive.glob("*.png"))
    assert "a.png" in names and "a-1.png" in names


def test_scan_aborts_when_llm_down(env):
    with pytest.raises(LLMUnavailable):
        scan_inbox(env.conn, env.cfg, DownLLM([]), today=D)
    assert len(list(env.cfg.inbox.iterdir())) == 1 and entries(env.conn) == []


def test_failed_file_stays_in_inbox(env):
    def boom(i):
        raise RuntimeError("x")
    r = scan_inbox(env.conn, env.cfg, FakeLLM([]), ocr=boom, today=D)
    assert len(r.errors) == 1
    assert len(list(env.cfg.inbox.iterdir())) == 1
    assert entries(env.conn) == []


def test_multipage_pdf_each_page_an_entry_atomic(env):
    pages = [Image.new("RGB", (20, 20), c) for c in ("white", "black")]
    (env.cfg.inbox / "a.png").unlink()
    pages[0].save(env.cfg.inbox / "r.pdf", save_all=True, append_images=pages[1:])
    r = run(env, [ok_fields(), ok_fields(shop="B", total="3.00")], text="12.50 3.00")
    assert r.added == 2
    assert sorted(e.image_path[-7:] for e in entries(env.conn)) == ["-p0.png", "-p1.png"]
    h = env.conn.execute("SELECT COUNT(*) FROM processed_files").fetchone()[0]
    assert h == 1


def test_failure_on_second_page_rolls_back_first(env):
    pages = [Image.new("RGB", (20, 20), c) for c in ("white", "black")]
    (env.cfg.inbox / "a.png").unlink()
    pages[0].save(env.cfg.inbox / "r.pdf", save_all=True, append_images=pages[1:])
    r = run(env, [ok_fields(), RuntimeError("boom")])
    assert len(r.errors) == 1
    assert entries(env.conn) == []
    assert env.conn.execute("SELECT COUNT(*) FROM processed_files").fetchone()[0] == 0
    assert (env.cfg.inbox / "r.pdf").exists()


def two_page_pdf(env):
    pages = [Image.new("RGB", (20, 20), c) for c in ("white", "black")]
    (env.cfg.inbox / "a.png").unlink()
    pages[0].save(env.cfg.inbox / "r.pdf", save_all=True, append_images=pages[1:])


def test_no_open_transaction_during_ocr_or_llm(env):
    two_page_pdf(env)
    seen = []

    class SpyLLM(FakeLLM):
        def extract_receipt(self, text, categories=None):
            seen.append(("llm", env.conn.in_transaction))
            return super().extract_receipt(text, categories)

    def ocr(img):
        seen.append(("ocr", env.conn.in_transaction))
        return "12.50 3.00"

    r = scan_inbox(env.conn, env.cfg, SpyLLM([ok_fields(), ok_fields(shop="B", total="3.00")]),
                   ocr=ocr, today=D)
    assert r.added == 2 and not r.errors
    assert seen == [("ocr", False), ("llm", False), ("ocr", False), ("llm", False)]
    assert not env.conn.in_transaction


def test_duplicate_pages_within_one_file_flagged(env):
    two_page_pdf(env)
    r = run(env, [ok_fields(), ok_fields()])
    assert sorted(e.status for e in entries(env.conn)) == ["ok", "suspected_duplicate"]
    assert (r.added, r.review) == (1, 1)
