"""Voice entries: dictated utterance (+ optional GPS) -> verified entry."""
import re
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, ValidationError

from tally import categories as cats
from tally import repo
from tally.llm import ExtractionError, LLMClient, UtteranceFields
from tally.money import format_cents, to_cents
from tally.places import resolve_place
from tally.verify import sane_date

_AMOUNT_ONLY = re.compile(r"^\$?\d+(\.\d{1,2})?$")
LARGE_CENTS = 50000  # over $500.00 in one cash purchase: ask the user to check


class VoiceItem(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    captured_at: AwareDatetime
    lat: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    lon: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)


class VoiceResult(BaseModel):
    id: str | None  # None only for an invalid item without a usable id
    status: Literal["recorded", "duplicate", "review", "invalid"]
    say: str


def validate_item(raw: Any) -> VoiceItem | VoiceResult:
    """A valid VoiceItem, or an 'invalid' result (the item is dropped, never stored)."""
    try:
        return VoiceItem.model_validate(raw)
    except ValidationError:
        rid = raw.get("id") if isinstance(raw, dict) else None
        ok = isinstance(rid, str) and 1 <= len(rid) <= 64
        return VoiceResult(id=rid if ok else None, status="invalid", say="")


def _say(shop: str | None, cents: int, category: str, review: bool, lang: str, conn) -> str:
    amount, cat = format_cents(cents), cats.label(category, lang, conn)
    if lang == "zh":
        s = f"已记录：{shop or '未知商店'} {amount}，{cat}"
        return s + "，请确认" if review else s
    s = f"Recorded: {shop or 'Unknown shop'} {amount}, {cat}"
    return s + " — please check" if review else s


def _parse(conn, llm: LLMClient, text: str, captured) -> tuple[UtteranceFields | None, str | None]:
    """Returns (fields, failure_reason)."""
    stripped = text.strip()
    if _AMOUNT_ONLY.match(stripped):
        return UtteranceFields(shop=None, amount=Decimal(stripped.lstrip("$")),
                               date=None, category=None), None
    try:
        return llm.parse_utterance(text, captured, categories=cats.all_slugs(conn)), None
    except ExtractionError:
        return None, "extraction_failed"


def _handle_one(conn, llm: LLMClient, it: VoiceItem, lang: str) -> VoiceResult:
    exists = conn.execute("SELECT 1 FROM entries WHERE client_id = ?", (it.id,)).fetchone()
    if exists:
        return VoiceResult(id=it.id, status="duplicate", say="")
    captured = it.captured_at.date()
    f, failure = _parse(conn, llm, it.text, captured)
    cents = to_cents(f.amount) if f else None
    spoken = f.shop if f else None
    try:
        place = resolve_place(conn, it.lat, it.lon, spoken, commit=False)
        shop = place.shop
        category = ((repo.confirmed_category(conn, shop) if shop else None)
                    or cats.normalize(f.category if f else None, conn))
        sane = sane_date(f.date, captured) if f else None
        bad_date = f is not None and f.date is not None and sane is None
        reason = None
        if cents is None:
            reason = failure or "no_amount"
        elif cents > LARGE_CENTS:
            reason = "large_amount"
        elif shop is None:
            reason = "unknown_place"
        elif place.ambiguous:
            reason = "ambiguous_place"
        elif bad_date:
            reason = "bad_date"
        d = sane or captured
        entry = repo.Entry(id=None, source="voice", shop=shop, date=d,
                           amount_cents=cents or 0, category=category,
                           status="needs_review" if reason else "ok", reason=reason,
                           utterance=it.text, client_id=it.id, place_id=place.place_id)
        repo.add_entry(conn, entry, commit=False)
        conn.commit()
    except repo.DuplicateClientId:
        conn.rollback()
        return VoiceResult(id=it.id, status="duplicate", say="")
    except BaseException:
        conn.rollback()
        raise
    return VoiceResult(id=it.id, status="review" if reason else "recorded",
                       say=_say(shop, cents or 0, category, bool(reason), lang, conn))


def handle_voice_batch(conn, llm: LLMClient, items: list[VoiceItem | VoiceResult],
                       lang: str) -> list[VoiceResult]:
    """Items already rejected by validate_item pass through as their invalid result."""
    return [it if isinstance(it, VoiceResult) else _handle_one(conn, llm, it, lang)
            for it in items]
