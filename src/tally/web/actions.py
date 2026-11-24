"""State-changing dashboard routes (POST). All are CSRF-guarded."""
import threading
from datetime import date

from fastapi import Depends, FastAPI, Form, HTTPException

from tally import categories, ingest, repo
from tally.config import Config
from tally.llm import LLMClient, LLMUnavailable
from tally.money import parse_amount
from tally.web import i18n
from tally.web.common import get_lang, safe_next, see_other, session, set_flash
from tally.web.security import make_csrf_guard

SSID_MAX = 64
_scan_lock = threading.Lock()


def _amount(s: str) -> int | None:
    try:
        cents = parse_amount(s)
    except ValueError:
        return None
    return cents if cents > 0 else None


def _date(s: str) -> date | None:
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        return None


def register_actions(app: FastAPI, cfg: Config, llm: LLMClient) -> None:
    guard = [Depends(make_csrf_guard(cfg))]

    def flash(conn, key: str, **kw) -> None:
        set_flash(conn, i18n.t(key, get_lang(conn)).format(**kw))

    def parse_entry_fields(conn, date_s, amount_s, category):
        """(fields, error_key). Fields are validated for use with repo calls."""
        d, cents = _date(date_s), _amount(amount_s)
        if d is None:
            return None, "err_date"
        if cents is None:
            return None, "err_amount"
        if not categories.is_valid(category, conn):
            return None, "err_category"
        return {"date": d, "amount_cents": cents, "category": category}, None

    @app.post("/entries/{entry_id}", dependencies=guard)
    def update_entry(entry_id: int, shop: str = Form(""), date_: str = Form("", alias="date"),
                     amount: str = Form(""), category: str = Form("other")):
        with session(cfg) as conn:
            e = repo.get_entry(conn, entry_id)
            if e is None or e.status == "deleted":
                raise HTTPException(404)
            fields, err = parse_entry_fields(conn, date_, amount, category)
            if err:
                flash(conn, err)
                return see_other(f"/entries/{entry_id}")
            new_shop = shop.strip() or None
            repo.update_entry(conn, entry_id, status="ok", reason=None, **fields)
            if new_shop != e.shop:
                if new_shop:
                    repo.name_entry_shop(conn, entry_id, new_shop)
                else:
                    repo.update_entry(conn, entry_id, shop=None)
            if category != (e.category or "other") and new_shop:
                repo.remember_shop_category(conn, new_shop, category)
            flash(conn, "flash_saved")
            return see_other("/entries?status=review")

    @app.post("/entries/{entry_id}/delete", dependencies=guard)
    def delete_entry(entry_id: int):
        with session(cfg) as conn:
            if repo.get_entry(conn, entry_id) is None:
                raise HTTPException(404)
            repo.update_entry(conn, entry_id, status="deleted")
            flash(conn, "flash_deleted")
            return see_other("/entries?status=review")

    @app.post("/entries", dependencies=guard)
    def add_entry(shop: str = Form(""), date_: str = Form("", alias="date"),
                  amount: str = Form(""), category: str = Form("other"),
                  next: str = Form("/")):
        with session(cfg) as conn:
            fields, err = parse_entry_fields(conn, date_, amount, category)
            if err:
                flash(conn, err)
            else:
                repo.add_entry(conn, repo.Entry(id=None, source="manual",
                                                shop=shop.strip() or None, **fields))
                flash(conn, "flash_added")
            return see_other(safe_next(next, "/"))

    @app.post("/withdrawals", dependencies=guard)
    def add_withdrawal(date_: str = Form("", alias="date"), amount: str = Form(""),
                       next: str = Form("/")):
        with session(cfg) as conn:
            d, cents = _date(date_), _amount(amount)
            if d is None or cents is None:
                flash(conn, "err_date" if d is None else "err_amount")
            else:
                repo.add_withdrawal(conn, d, cents)
                flash(conn, "flash_withdrawal")
            return see_other(safe_next(next, "/"))

    @app.post("/withdrawals/{withdrawal_id}/delete", dependencies=guard)
    def delete_withdrawal(withdrawal_id: int, next: str = Form("/entries?status=withdrawals")):
        with session(cfg) as conn:
            repo.delete_withdrawal(conn, withdrawal_id)
            flash(conn, "flash_deleted")
            return see_other(safe_next(next, "/entries?status=withdrawals"))

    @app.post("/scan", dependencies=guard)
    def scan(next: str = Form("/")):
        with session(cfg) as conn:
            if not _scan_lock.acquire(blocking=False):
                flash(conn, "err_scan_busy")
                return see_other(safe_next(next, "/"))
            try:
                res = ingest.scan_inbox(conn, cfg, llm)
            except LLMUnavailable as ex:
                flash(conn, "err_llm", msg=str(ex))
            else:
                flash(conn, "flash_scan", added=res.added, review=res.review,
                      skipped=res.skipped_files, card=res.card)
                if res.errors:
                    lang = get_lang(conn)
                    extra = i18n.t("flash_scan_errors", lang).format(errors="; ".join(res.errors))
                    set_flash(conn, (repo.get_setting(conn, "flash") or "") + extra)
            finally:
                _scan_lock.release()
            return see_other(safe_next(next, "/"))

    @app.post("/lang", dependencies=guard)
    def set_lang(lang: str = Form(""), next: str = Form("/")):
        if lang not in i18n.LANGS:
            raise HTTPException(400, "Unknown language")
        with session(cfg) as conn:
            repo.set_setting(conn, "lang", lang)
            return see_other(safe_next(next, "/"))

    @app.post("/categories", dependencies=guard)
    def add_category(slug: str = Form(""), en: str = Form(""), zh: str = Form(""),
                     next: str = Form("/")):
        en, zh = en.strip()[:40], zh.strip()[:40]
        with session(cfg) as conn:
            try:
                if not en:
                    raise ValueError("label required")
                categories.add_custom(conn, slug.strip(), en, zh or en)
            except ValueError:
                flash(conn, "err_category_new")
            else:
                flash(conn, "flash_category")
            return see_other(safe_next(next, "/"))

    @app.post("/pairing/regenerate", dependencies=guard)
    def regenerate():
        with session(cfg) as conn:
            repo.regenerate_token(conn)
            flash(conn, "flash_token")
            return see_other("/pairing")

    @app.post("/pairing/ssid", dependencies=guard)
    def save_ssid(ssid: str = Form("")):
        with session(cfg) as conn:
            repo.set_setting(conn, "home_ssid", ssid.strip()[:SSID_MAX])
            flash(conn, "flash_ssid")
            return see_other("/pairing")
