"""Receipt ingest: inbox files -> OCR -> LLM extraction -> verified entries."""
import hashlib
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from PIL import Image

from tally import categories as cats
from tally import repo
from tally.config import Config
from tally.llm import ExtractionError, LLMClient
from tally.money import to_cents
from tally.ocr import SUPPORTED, load_pages, ocr_image
from tally.verify import amount_in_text, cash_and_change, sane_date

LOW_CONFIDENCE = 0.7
# How far the model's total may be from (cash - change) before the receipt goes to review.
# Covers penny rounding and similar adjustments.
CASH_TOLERANCE_CENTS = 100


@dataclass
class ScanResult:
    added: int = 0
    review: int = 0
    skipped_files: int = 0
    card: int = 0
    errors: list[str] = field(default_factory=list)


def _unique_dest(dir_: Path, name: str) -> Path:
    dest = dir_ / name
    stem, suffix, n = Path(name).stem, Path(name).suffix, 0
    while dest.exists():
        n += 1
        dest = dir_ / f"{stem}-{n}{suffix}"
    return dest


def _failed_entry(reason: str, today: date, image_path: str, text: str) -> repo.Entry:
    return repo.Entry(id=None, source="receipt", shop=None, date=today, amount_cents=0,
                      category="other", status="needs_review", reason=reason,
                      image_path=image_path, ocr_text=text)


def _is_duplicate(conn, shop: str, d: date, cents: int, pending: list[repo.Entry]) -> bool:
    """Against counted entries in the DB and earlier pages of this file (not yet stored)."""
    return repo.find_duplicate(conn, shop, d, cents) is not None or any(
        p.shop == shop and p.date == d and p.amount_cents == cents
        and p.status in ("ok", "needs_review") for p in pending)


def _build_entry(conn, llm: LLMClient, text: str, image_path: str, today: date,
                 pending: list[repo.Entry]) -> repo.Entry:
    if not text.strip():
        return _failed_entry("no_total", today, image_path, text)
    try:
        f = llm.extract_receipt(text, categories=cats.all_slugs(conn))
    except ExtractionError:
        return _failed_entry("extraction_failed", today, image_path, text)

    cents = to_cents(f.total)
    payment = f.payment_method
    # CASH and CHANGE lines give the exact cash spent; prefer that over the model's total.
    # The model often mistakes the CASH (tendered) line for the total.
    cash_mismatch = False
    if cc := cash_and_change(text):
        cash, change = cc
        paid = cash - change
        cash_mismatch = (cents is not None and cents != cash
                         and abs(cents - paid) > CASH_TOLERANCE_CENTS)
        cents, payment = paid, "cash"
    d = sane_date(f.date, today)
    shop = (f.shop or "").strip() or None
    category = (repo.confirmed_category(conn, shop) if shop else None) or f.category
    e = repo.Entry(id=None, source="receipt", shop=shop, date=d or today,
                   amount_cents=cents or 0, category=cats.normalize(category, conn),
                   payment_method=payment, image_path=image_path, ocr_text=text)

    if payment == "card":
        e.status = "card_skipped"
    elif shop and cents and _is_duplicate(conn, shop, e.date, cents, pending):
        e.status = "suspected_duplicate"
    else:
        reason = None
        if cents is None:
            reason = "no_total"
        elif cash_mismatch or (cc is None and not amount_in_text(cents, text)):
            reason = "amount_mismatch"
        elif shop is None:
            reason = "no_shop"
        elif f.confidence < LOW_CONFIDENCE:
            reason = "low_confidence"
        elif d is None:
            reason = "bad_date"
        if reason:
            e.status, e.reason = "needs_review", reason
    if d is None and e.reason is None:
        e.reason = "bad_date"  # keep the note on card/duplicate entries too
    return e


def _process_file(conn, llm: LLMClient, ocr, path: Path, h: str, out_dir: Path,
                  today: date, res: ScanResult) -> None:
    saved: list[Path] = []
    built: list[repo.Entry] = []
    stored = False
    try:
        # Slow work first (render, OCR, LLM) with no write transaction open...
        for i, page in enumerate(load_pages(path)):
            png = out_dir / f"{h[:16]}-p{i}.png"
            page.save(png, format="PNG")
            saved.append(png)
            text = ocr(page)
            built.append(_build_entry(conn, llm, text, str(png), today, built))
        # ...then one short transaction for the whole file. Claiming the hash first takes the
        # write lock, so a scan in another process that got there first is seen here.
        if repo.mark_processed(conn, h, path.name, commit=False):
            for e in built:
                repo.add_entry(conn, e, commit=False)
            conn.commit()
            stored = True
    finally:
        if not stored:
            conn.rollback()
            for p in saved:
                p.unlink(missing_ok=True)
    if not stored:  # no exception: another scan recorded this file first
        res.skipped_files += 1
        return
    counts = {"ok": 0, "needs_review": 0, "suspected_duplicate": 0, "card_skipped": 0}
    for e in built:
        counts[e.status] += 1
    res.added += counts["ok"]
    res.review += counts["needs_review"] + counts["suspected_duplicate"]
    res.card += counts["card_skipped"]


def scan_inbox(conn, cfg: Config, llm: LLMClient,
               ocr: Callable[[Image.Image], str] = ocr_image,
               today: date | None = None) -> ScanResult:
    llm.health()  # LLMUnavailable propagates before anything is touched
    today = today or date.today()
    res = ScanResult()
    out_dir = cfg.archive / f"{today:%Y}" / f"{today:%m}"  # pages and originals, by scan date
    files = sorted((p for p in cfg.inbox.iterdir()
                    if p.is_file() and p.suffix.lower() in SUPPORTED), key=lambda p: p.name)
    if files:
        out_dir.mkdir(parents=True, exist_ok=True)
    for path in files:
        try:
            h = hashlib.sha256(path.read_bytes()).hexdigest()
            if repo.is_processed(conn, h):
                res.skipped_files += 1
            else:
                _process_file(conn, llm, ocr, path, h, out_dir, today, res)
            if path.exists():  # a concurrent scan may already have archived it
                shutil.move(str(path), _unique_dest(out_dir, path.name))
        except Exception as ex:
            res.errors.append(f"{path.name}: {ex}")
    return res
