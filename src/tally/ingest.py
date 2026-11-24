"""Receipt ingest: inbox files -> OCR -> LLM extraction -> verified entries."""
import hashlib
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from PIL import Image

from tally import categories as cats
from tally import repo
from tally.config import Config
from tally.llm import ExtractionError, LLMClient
from tally.ocr import SUPPORTED, load_pages, ocr_image
from tally.verify import amount_in_text, sane_date

LOW_CONFIDENCE = 0.7


@dataclass
class ScanResult:
    added: int = 0
    review: int = 0
    skipped_files: int = 0
    card: int = 0
    errors: list[str] = field(default_factory=list)


def _cents(total: Decimal | None) -> int | None:
    """Dollars to cents (ROUND_HALF_UP); None for missing, non-finite or non-positive."""
    if total is None or not total.is_finite() or total <= 0:
        return None
    return int((total * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _slug(raw: str | None, conn) -> str:
    s = (raw or "").strip().lower()
    return s if cats.is_valid(s, conn) else "other"


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


def _build_entry(conn, llm: LLMClient, text: str, image_path: str, today: date) -> repo.Entry:
    if not text.strip():
        return _failed_entry("no_total", today, image_path, text)
    try:
        f = llm.extract_receipt(text, categories=cats.all_slugs(conn))
    except ExtractionError:
        return _failed_entry("extraction_failed", today, image_path, text)

    cents = _cents(f.total)
    d = sane_date(f.date, today)
    shop = (f.shop or "").strip() or None
    category = (repo.confirmed_category(conn, shop) if shop else None) or f.category
    e = repo.Entry(id=None, source="receipt", shop=shop, date=d or today,
                   amount_cents=cents or 0, category=_slug(category, conn),
                   payment_method=f.payment_method, image_path=image_path, ocr_text=text)

    if f.payment_method == "card":
        e.status = "card_skipped"
    elif shop and cents and repo.find_duplicate(conn, shop, e.date, cents):
        e.status = "suspected_duplicate"
    else:
        reason = None
        if cents is None:
            reason = "no_total"
        elif not amount_in_text(cents, text):
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


def _process_file(conn, cfg: Config, llm: LLMClient, ocr, path: Path, h: str,
                  today: date, res: ScanResult) -> None:
    out_dir = cfg.archive / f"{today:%Y}" / f"{today:%m}"
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    counts = {"ok": 0, "needs_review": 0, "suspected_duplicate": 0, "card_skipped": 0}
    try:
        for i, page in enumerate(load_pages(path)):
            png = out_dir / f"{h[:16]}-p{i}.png"
            page.save(png, format="PNG")
            saved.append(png)
            text = ocr(page)
            e = _build_entry(conn, llm, text, str(png), today)
            repo.add_entry(conn, e, commit=False)
            counts[e.status] += 1
        repo.mark_processed(conn, h, path.name, commit=False)
        conn.commit()
    except BaseException:
        conn.rollback()
        for p in saved:
            p.unlink(missing_ok=True)
        raise
    res.added += counts["ok"]
    res.review += counts["needs_review"] + counts["suspected_duplicate"]
    res.card += counts["card_skipped"]


def scan_inbox(conn, cfg: Config, llm: LLMClient,
               ocr: Callable[[Image.Image], str] = ocr_image,
               today: date | None = None) -> ScanResult:
    llm.health()  # LLMUnavailable propagates before anything is touched
    today = today or date.today()
    res = ScanResult()
    files = sorted((p for p in cfg.inbox.iterdir()
                    if p.is_file() and p.suffix.lower() in SUPPORTED), key=lambda p: p.name)
    for path in files:
        try:
            h = hashlib.sha256(path.read_bytes()).hexdigest()
            if repo.is_processed(conn, h):
                res.skipped_files += 1
            else:
                _process_file(conn, cfg, llm, ocr, path, h, today, res)
            shutil.move(str(path), _unique_dest(cfg.archive, path.name))
        except Exception as ex:
            res.errors.append(f"{path.name}: {ex}")
    return res
