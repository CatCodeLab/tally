import re
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import NoLLM, mk

from tally import categories, repo
from tally.llm import LLMUnavailable
from tally.repo import add_entry, get_entry
from tally.web import app as web_app
from tally.web.app import create_dashboard_app
from tally.web.i18n import STRINGS, t

TODAY = date.today()
WEB = Path(web_app.__file__).parent


@pytest.fixture
def dash(tmp_config):
    return TestClient(create_dashboard_app(tmp_config, NoLLM()), base_url="http://127.0.0.1:8765",
                      follow_redirects=False)


def csrf(c):
    return re.search(r'name="csrf" value="([^"]+)"', c.get("/").text).group(1)


def post(c, path, **data):
    return c.post(path, data={"csrf": csrf(c), **data})


def test_rejects_foreign_host(dash):
    assert dash.get("/", headers={"Host": "evil.example"}).status_code == 400
    assert dash.get("/", headers={"Host": "127.0.0.1.evil.example"}).status_code == 400
    assert dash.get("/", headers={"Host": "localhost:8765"}).status_code == 200


def test_post_requires_csrf(dash):
    assert dash.post("/withdrawals", data={"amount": "20", "date": "2026-11-01"}).status_code == 403
    assert dash.post("/withdrawals", data={"amount": "20", "date": "2026-11-01",
                                           "csrf": "wrong"}).status_code == 403
    r = dash.post("/withdrawals", data={"amount": "20", "date": "2026-11-01", "csrf": csrf(dash)})
    assert r.status_code in (200, 303)


def test_post_rejects_foreign_origin(dash):
    r = dash.post("/lang", data={"lang": "zh", "csrf": csrf(dash)},
                  headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    r = dash.post("/lang", data={"lang": "zh", "csrf": csrf(dash)},
                  headers={"Origin": "http://localhost:8765"})
    assert r.status_code == 303


def test_no_cors_headers(dash):
    r = dash.get("/", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_shop_name_escaped(dash, conn):
    add_entry(conn, mk(shop="<script>alert(1)</script>", date=TODAY))
    html = dash.get("/").text
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html
    eid = conn.execute("SELECT id FROM entries").fetchone()[0]
    page = dash.get(f"/entries/{eid}").text
    assert "<script>alert(1)" not in page
    assert "<script>alert(1)" not in dash.get("/entries").text


def test_chart_json_cannot_break_out_of_script(dash, conn):
    categories.add_custom(conn, "evil", "</script><b>x", "y")
    add_entry(conn, mk(category="evil", date=TODAY))
    assert "</script><b>" not in dash.get("/").text


def test_language_switch(dash):
    dash.post("/lang", data={"lang": "zh", "csrf": csrf(dash)})
    assert "去向不明" in dash.get("/").text
    assert dash.post("/lang", data={"lang": "fr", "csrf": csrf(dash)}).status_code == 400


def test_negative_unaccounted_label(dash, conn):
    add_entry(conn, mk(amount_cents=5000, date=TODAY))
    html = dash.get("/").text
    assert "−$50.00" in html and "spent from earlier cash" in html
    dash.post("/lang", data={"lang": "zh", "csrf": csrf(dash)})
    assert "花的是之前的现金" in dash.get("/").text


def test_overview_totals_and_unconfirmed(dash, conn):
    repo.add_withdrawal(conn, TODAY, 10000)
    add_entry(conn, mk(amount_cents=2000, date=TODAY, status="needs_review", reason="no_shop"))
    html = dash.get("/").text
    assert "$100.00" in html and "incl. $20.00 unconfirmed" in html and "$80.00" in html
    assert "1 to review" in html


def test_range_navigation_and_presets(dash, conn):
    add_entry(conn, mk(shop="Old", amount_cents=700, date=date(2020, 5, 3)))
    html = dash.get("/?start=2020-05-01&end=2020-05-31").text
    assert "Old" in html and "$7.00" in html
    assert "start=2020-04-01" in html and "end=2020-04-30" in html  # prev link
    assert dash.get("/?preset=last_month").status_code == 200
    assert dash.get("/?start=garbage&end=2020-01-01&category=nope").status_code == 200


def test_edit_remembers_category(dash, conn):
    eid = add_entry(conn, mk(shop="Cafe", category="other", status="needs_review",
                             reason="no_shop", date=TODAY))
    r = post(dash, f"/entries/{eid}", shop="Cafe", date=TODAY.isoformat(), amount="3.50",
             category="food")
    assert r.status_code == 303
    e = get_entry(conn, eid)
    assert (e.status, e.reason, e.category, e.amount_cents) == ("ok", None, "food", 350)
    assert repo.confirmed_category(conn, "Cafe") == "food"


def test_edit_renames_shop_and_place(dash, conn):
    conn.execute("INSERT INTO places(shop) VALUES (NULL)")
    pid = conn.execute("SELECT id FROM places").fetchone()[0]
    eid = add_entry(conn, mk(shop=None, place_id=pid, status="needs_review",
                             reason="unknown_place", date=TODAY))
    post(dash, f"/entries/{eid}", shop="Deli", date=TODAY.isoformat(), amount="1",
         category="other")
    assert get_entry(conn, eid).shop == "Deli"
    assert conn.execute("SELECT shop FROM places WHERE id = ?", (pid,)).fetchone()[0] == "Deli"


def test_edit_rejects_bad_input_without_confirming(dash, conn):
    eid = add_entry(conn, mk(status="needs_review", reason="no_total", date=TODAY))
    post(dash, f"/entries/{eid}", shop="x", date="nope", amount="1", category="other")
    post(dash, f"/entries/{eid}", shop="x", date=TODAY.isoformat(), amount="abc", category="other")
    post(dash, f"/entries/{eid}", shop="x", date=TODAY.isoformat(), amount="1", category="bogus")
    assert get_entry(conn, eid).status == "needs_review"


def test_not_card_counts_it(dash, conn):
    eid = add_entry(conn, mk(status="card_skipped", amount_cents=900, date=TODAY))
    assert "Not card" in dash.get(f"/entries/{eid}").text
    post(dash, f"/entries/{eid}", shop="S", date=TODAY.isoformat(), amount="9", category="other")
    assert get_entry(conn, eid).status == "ok"


def test_delete_hides_entry(dash, conn):
    eid = add_entry(conn, mk(date=TODAY))
    assert post(dash, f"/entries/{eid}/delete").status_code == 303
    assert get_entry(conn, eid).status == "deleted"
    assert dash.get(f"/entries/{eid}").status_code == 404


def test_manual_add_and_withdrawal(dash, conn):
    post(dash, "/entries", shop="Kiosk", date=TODAY.isoformat(), amount="$1,234.50",
         category="food", next="/")
    e = conn.execute("SELECT source, shop, amount_cents FROM entries").fetchone()
    assert tuple(e) == ("manual", "Kiosk", 123450)
    post(dash, "/withdrawals", date=TODAY.isoformat(), amount="50")
    assert repo.sum_withdrawals(conn, TODAY, TODAY) == 5000
    post(dash, "/withdrawals", date=TODAY.isoformat(), amount="-5")
    assert repo.sum_withdrawals(conn, TODAY, TODAY) == 5000


def test_entries_review_ignores_date_and_card_tab(dash, conn):
    add_entry(conn, mk(shop="OldReview", date=date(2019, 1, 1), status="needs_review"))
    add_entry(conn, mk(shop="Dup", date=date(2019, 1, 2), status="suspected_duplicate"))
    add_entry(conn, mk(shop="CardShop", date=TODAY, status="card_skipped"))
    add_entry(conn, mk(shop="VoiceShop", date=TODAY, source="voice", utterance="hi"))
    html = dash.get("/entries?status=review").text
    assert "OldReview" in html and "Dup" in html and "CardShop" not in html
    assert "CardShop" in dash.get("/entries?status=card").text
    assert "🎤" in dash.get("/entries").text


def test_review_reason_labels_translated(dash, conn):
    add_entry(conn, mk(date=TODAY, status="needs_review", reason="amount_mismatch"))
    assert "Amount not found in the receipt text" in dash.get("/entries?status=review").text
    dash.post("/lang", data={"lang": "zh", "csrf": csrf(dash)})
    assert "收据文字里找不到这个金额" in dash.get("/entries?status=review").text


def test_scan_flashes_counts(dash, conn):
    r = post(dash, "/scan", next="/")
    assert r.status_code == 303
    assert "Scan done: 0 added" in dash.get("/").text
    assert "Scan done" not in dash.get("/").text  # flash is shown once


def test_scan_llm_unavailable_flash(tmp_config):
    class Down(NoLLM):
        def health(self):
            raise LLMUnavailable("ollama is down <b>")

    c = TestClient(create_dashboard_app(tmp_config, Down()), base_url="http://127.0.0.1:8765",
                   follow_redirects=False)
    post(c, "/scan", next="/")
    html = c.get("/").text
    assert "ollama is down &lt;b&gt;" in html


def test_add_category(dash, conn):
    post(dash, "/categories", slug="pets", en="Pets", zh="宠物")
    assert "pets" in categories.all_slugs(conn)
    post(dash, "/categories", slug="Bad Slug", en="x", zh="y")
    assert "Bad Slug" not in categories.all_slugs(conn)


def test_open_redirect_blocked(dash):
    r = post(dash, "/withdrawals", date=TODAY.isoformat(), amount="5", next="//evil.example/x")
    assert r.headers["location"] == "/"


def test_image_served_from_archive_only(dash, conn, tmp_config):
    img = tmp_config.archive / "a.png"
    img.write_bytes(b"\x89PNG fake")
    ok = add_entry(conn, mk(image_path=str(img)))
    bad = add_entry(conn, mk(image_path="/etc/passwd"))
    assert dash.get(f"/images/{ok}").status_code == 200
    assert dash.get(f"/images/{bad}").status_code == 404


def test_image_path_traversal(dash, conn, tmp_config):
    sneaky = tmp_config.archive / ".." / "tally.db"
    eid = add_entry(conn, mk(image_path=str(sneaky)))
    assert dash.get(f"/images/{eid}").status_code == 404
    assert dash.get("/images/99999").status_code == 404


def test_pairing_page(dash, conn):
    html = dash.get("/pairing").text
    token = repo.get_setting(conn, repo.TOKEN_KEY)
    assert token in html and ".local" in html and "8766" in html
    post(dash, "/pairing/ssid", ssid="HomeNet")
    assert repo.get_setting(conn, "home_ssid") == "HomeNet"
    post(dash, "/pairing/regenerate")
    assert repo.get_setting(conn, repo.TOKEN_KEY) != token


def test_i18n_keys_complete():
    assert set(STRINGS["en"]) == set(STRINGS["zh"])


def test_template_keys_exist():
    used = set()
    for p in (WEB / "templates").glob("*.html"):
        used |= set(re.findall(r"\bt\('([a-z_0-9]+)'\)", p.read_text()))
    used |= {f"preset_{p}" for p in ("this_month", "last_month", "last_3_months", "this_year")}
    used |= {f"status_{s}" for s in ("ok", "needs_review", "suspected_duplicate", "card_skipped")}
    used |= {f"reason_{r}" for r in ("no_total", "amount_mismatch", "no_shop", "low_confidence",
                                      "bad_date", "extraction_failed", "no_amount",
                                      "unknown_place", "ambiguous_place")}
    assert used <= set(STRINGS["en"]), used - set(STRINGS["en"])
    assert t("withdrawn", "zh") != t("withdrawn", "en")


def test_no_external_urls():
    for p in list((WEB / "templates").glob("*")) + [WEB / "static" / "app.css",
                                                    WEB / "static" / "app.js"]:
        assert not re.search(r"""(src|href|url\()\s*=?\s*["']?(https?:)?//""", p.read_text()), p
    chart = WEB / "static" / "chart.umd.min.js"
    assert chart.exists()
    assert not re.search(r"""(src|href)\s*=\s*["']https?://""", chart.read_text())
