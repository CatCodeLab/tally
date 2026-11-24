"""Read-only dashboard pages (GET routes)."""
import socket
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from tally import categories, dates, repo, report
from tally.config import Config
from tally.money import format_cents
from tally.repo import Filters
from tally.web import i18n
from tally.web.common import get_lang, pop_flash, session
from tally.web.security import ensure_csrf_secret

PRESETS = ("this_month", "last_month", "last_3_months", "this_year")
PALETTE = ["#3b82f6", "#10b981", "#f59e0b", "#a78bfa", "#ef4444", "#14b8a6",
           "#ec4899", "#84cc16", "#6366f1", "#f97316", "#64748b"]
STATUS_TABS = {"review": ("needs_review", "suspected_duplicate"),
               "card": ("card_skipped",)}


def _parse_date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def parse_range(q, today: date) -> tuple[dates.DateRange, str | None]:
    """Explicit start+end win; else a preset (default this_month). Returns (range, preset)."""
    s, e = _parse_date(q.get("start")), _parse_date(q.get("end"))
    if s and e and s <= e:
        return dates.DateRange(s, e), None
    name = q.get("preset") if q.get("preset") in PRESETS else "this_month"
    return dates.preset(name, today), name


def range_label(r: dates.DateRange, lang: str) -> str:
    if lang == "zh":
        return f"{r.start.isoformat()} 至 {r.end.isoformat()}"
    a = f"{r.start:%b} {r.start.day}" + ("" if r.start.year == r.end.year else f", {r.start.year}")
    return f"{a} – {r.end:%b} {r.end.day}, {r.end.year}"


def bucket_label(key: str, gran: str, lang: str, multi_year: bool) -> str:
    if gran == "week":
        return key[5:]
    y, m = int(key[:4]), int(key[5:])
    if lang == "zh":
        return f"{y}-{m:02d}" if multi_year else f"{m}月"
    name = date(y, m, 1).strftime("%b")
    return f"{name} {y}" if multi_year else name


def make_link(base: dict):
    def link(path: str = "/", **over) -> str:
        p = {k: v for k, v in {**base, **over}.items() if v not in (None, "")}
        return path + ("?" + urlencode(p) if p else "")
    return link


def register_pages(app: FastAPI, cfg: Config, templates) -> None:
    def render(request: Request, conn, name: str, **ctx):
        lang = get_lang(conn)
        ctx.update(lang=lang, csrf=ensure_csrf_secret(conn), flash=pop_flash(conn),
                   t=lambda key: i18n.t(key, lang), money=format_cents,
                   reason_label=lambda r: i18n.reason_label(r, lang),
                   here=request.url.path + (f"?{request.url.query}" if request.url.query else ""))
        return templates.TemplateResponse(request, name, ctx)

    def view_state(request: Request, conn):
        """Shared by overview and entries: range, filters and a link builder."""
        q = request.query_params
        r, active = parse_range(q, date.today())
        category = q.get("category") if q.get("category") in categories.all_slugs(conn) else None
        shop = q.get("shop") or None
        base = {"preset": active} if active else {"start": r.start.isoformat(),
                                                  "end": r.end.isoformat()}
        base.update(category=category, shop=shop)
        return r, active, category, shop, make_link(base)

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request):
        with session(cfg) as conn:
            lang = get_lang(conn)
            r, active, category, shop, link = view_state(request, conn)
            s = report.summary(conn, Filters(r.start, r.end, category, shop))
            slugs = categories.all_slugs(conn)
            gran = dates.granularity(r)
            cats = [{"slug": c, "label": categories.label(c, lang, conn), "cents": v,
                     "color": PALETTE[i % len(PALETTE)], "url": link(category=c)}
                    for i, (c, v) in enumerate(s.by_category)]
            multi_year = r.start.year != r.end.year
            chart = {"cats": cats,
                     "buckets": [{"label": bucket_label(k, gran, lang, multi_year), "cents": v}
                                 for k, v in s.buckets],
                     "gran": gran}
            shop_names = sorted({e.shop for e in repo.list_entries(
                conn, Filters(r.start, r.end)) if e.shop})
            if shop and shop not in shop_names:
                shop_names.append(shop)
            prev_r, next_r = dates.shift(r, -1), dates.shift(r, 1)
            return render(
                request, conn, "overview.html", s=s, chart=chart, cats=cats, gran=gran,
                range_label=range_label(r, lang), start=r.start.isoformat(),
                end=r.end.isoformat(), active=active, presets=PRESETS,
                category=category, shop=shop, shop_names=shop_names, link=link,
                prev_url=link(preset=None, start=prev_r.start.isoformat(),
                              end=prev_r.end.isoformat()),
                next_url=link(preset=None, start=next_r.start.isoformat(),
                              end=next_r.end.isoformat()),
                category_options=[(c, categories.label(c, lang, conn)) for c in slugs],
                today=date.today().isoformat(),
                top_shops=[(n, cents, cnt, link(shop=n)) for n, cents, cnt in s.top_shops])

    @app.get("/entries", response_class=HTMLResponse)
    def entries(request: Request):
        with session(cfg) as conn:
            lang = get_lang(conn)
            r, active, category, shop, link = view_state(request, conn)
            tab = request.query_params.get("status")
            if tab == "withdrawals":
                return render(request, conn, "entries.html", rows=[], tab=tab, link=link,
                              range_label=range_label(r, lang),
                              withdrawals=repo.list_withdrawals(conn, r.start, r.end))
            tab = tab if tab in STATUS_TABS else None
            if tab == "review":  # the review queue ignores the date range
                f = Filters(date.min, date.max, category, shop, STATUS_TABS[tab])
            elif tab == "card":
                f = Filters(r.start, r.end, category, shop, STATUS_TABS[tab])
            else:
                f = Filters(r.start, r.end, category, shop)
            rows = [(e, categories.label(e.category or "other", lang, conn))
                    for e in repo.list_entries(conn, f)]
            return render(request, conn, "entries.html", rows=rows, tab=tab, link=link,
                          range_label=range_label(r, lang))

    @app.get("/entries/{entry_id}", response_class=HTMLResponse)
    def entry_detail(request: Request, entry_id: int):
        with session(cfg) as conn:
            e = repo.get_entry(conn, entry_id)
            if e is None or e.status == "deleted":
                raise HTTPException(404)
            lang = get_lang(conn)
            options = [(c, categories.label(c, lang, conn)) for c in categories.all_slugs(conn)]
            return render(request, conn, "entry.html", e=e, category_options=options)

    @app.get("/images/{entry_id}")
    def image(entry_id: int):
        with session(cfg) as conn:
            e = repo.get_entry(conn, entry_id)
        if e is None or not e.image_path:
            raise HTTPException(404)
        try:
            path = Path(e.image_path).resolve()
            path.relative_to(cfg.archive.resolve())
        except (ValueError, OSError):
            raise HTTPException(404) from None
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path)

    @app.get("/pairing", response_class=HTMLResponse)
    def pairing(request: Request):
        with session(cfg) as conn:
            host = socket.gethostname().removesuffix(".local") + ".local"
            return render(request, conn, "pairing.html", host=host, port=cfg.voice_port,
                          token=repo.get_or_create_token(conn),
                          ssid=repo.get_setting(conn, "home_ssid", "") or "")

    @app.get("/pairing/guide", response_class=HTMLResponse)
    def pairing_guide(request: Request):
        # Packaged copy only, rendered as escaped text by Jinja autoescape.
        guide = (Path(__file__).parent / "guide" / "shortcut-setup.md").read_text(encoding="utf-8")
        with session(cfg) as conn:
            return render(request, conn, "guide.html", guide=guide)
