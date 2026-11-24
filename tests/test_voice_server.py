import pytest
from fastapi.testclient import TestClient

from datetime import date
from decimal import Decimal

from helpers import NoLLM, FakeLLM
from tally.llm import UtteranceFields
from tally import repo
from tally.voice_server import create_voice_app

T = "2026-11-24T12:00:00+00:00"


def it(i, text="40", **kw):
    return {"id": i, "text": text, "captured_at": T, **kw}


ITEM, ITEM_A, ITEM_B = it("u0"), it("a"), it("b", "12")


def auth(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture
def client(tmp_config, conn):
    return TestClient(create_voice_app(tmp_config, NoLLM()))


@pytest.fixture
def token(conn):
    return repo.get_or_create_token(conn)


def test_rejects_without_token(client, token):
    assert client.post("/api/voice", json={"items": [ITEM]}).status_code == 401
    assert client.post("/api/voice", json={"items": [ITEM]}, headers=auth("wrong")).status_code == 401
    for h in ({"Authorization": token}, {"Authorization": f"bearer {token}"},
              {"Authorization": f"Bearer  {token}"}, {"Authorization": f"Bearer {token} x"}):
        r = client.post("/api/voice", json={"items": [ITEM]}, headers=h)
        assert r.status_code == 401 and token not in r.text


def test_records_batch(tmp_config, token):
    fields = lambda shop, amt: UtteranceFields(  # noqa: E731
        shop=shop, amount=Decimal(amt), date=date(2026, 11, 24), category="food")
    c = TestClient(create_voice_app(tmp_config, FakeLLM([fields("Deli", "5"), fields("Cafe", "6")])))
    r = c.post("/api/voice", json={"items": [it("a", "Deli 5"), it("b", "Cafe 6")]},
               headers=auth(token))
    assert r.status_code == 200 and [x["status"] for x in r.json()["results"]] == ["recorded", "recorded"]
    assert r.json()["say"].endswith("(+1 synced)")


def test_review_batch_counts_synced(client, token):
    r = client.post("/api/voice", json={"items": [ITEM_A, ITEM_B]}, headers=auth(token))
    assert r.status_code == 200 and [x["status"] for x in r.json()["results"]] == ["review", "review"]
    assert r.json()["say"].endswith("(+1 synced)")


def test_single_item_no_suffix_and_zh(client, conn, token):
    r = client.post("/api/voice", json={"items": [ITEM]}, headers=auth(token))
    assert "synced" not in r.json()["say"]
    repo.set_setting(conn, "lang", "zh")
    r = client.post("/api/voice", json={"items": [ITEM_A, ITEM_B]}, headers=auth(token))
    assert r.json()["say"].endswith("（另同步 1 条）")


def test_duplicates_not_counted(client, token):
    client.post("/api/voice", json={"items": [ITEM_A]}, headers=auth(token))
    r = client.post("/api/voice", json={"items": [ITEM_A, ITEM_B]}, headers=auth(token))
    assert "synced" not in r.json()["say"]


def test_no_read_routes(client, token):
    for path in ["/", "/docs", "/redoc", "/openapi.json", "/api/entries", "/api/voice"]:
        assert client.get(path, headers=auth(token)).status_code == 404
    assert client.put("/api/voice", headers=auth(token)).status_code == 404


def test_regenerate_invalidates_old(client, conn, token):
    new = repo.regenerate_token(conn)
    assert new != token
    assert client.post("/api/voice", json={"items": [ITEM]}, headers=auth(token)).status_code == 401
    assert client.post("/api/voice", json={"items": [ITEM]}, headers=auth(new)).status_code == 200


def test_token_stable(conn):
    assert repo.get_or_create_token(conn) == repo.get_or_create_token(conn)


@pytest.mark.parametrize("body", [
    {"items": []}, {"items": [ITEM] * 201}, {}, {"items": "x"}, {"items": {"id": "x"}}, [],
])
def test_bad_envelope_422(client, token, body):
    assert client.post("/api/voice", json=body, headers=auth(token)).status_code == 422


@pytest.mark.parametrize("bad,rid", [
    ({"id": "x"}, "x"), (it("g", lat=91, lon=0), "g"), (it("g", lat=0, lon=181), "g"),
    (it("g", lat=-90.1, lon=0), "g"), (it("g", captured_at="2026-11-24T12:00:00"), "g"),
    (it("i" * 65), None), (it(7), None), ("not an object", None), ({}, None),
])
def test_bad_item_is_invalid_not_stored(client, conn, token, bad, rid):
    r = client.post("/api/voice", json={"items": [bad]}, headers=auth(token))
    assert r.status_code == 200
    assert r.json()["results"] == [{"id": rid, "status": "invalid", "say": ""}]
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0


def test_nan_inf_item_invalid(client, token):
    for v in ("NaN", "Infinity"):
        raw = ('{"items":[{"id":"g","text":"1","captured_at":"%s","lat":%s,"lon":0}]}' % (T, v))
        r = client.post("/api/voice", content=raw, headers={**auth(token), "content-type": "application/json"})
        assert r.status_code == 200 and r.json()["results"][0]["status"] == "invalid"


def test_mixed_batch_keeps_valid_items(client, conn, token):
    body = {"items": [{}, it("long", "x" * 600), it("ok", "40")]}
    r = client.post("/api/voice", json=body, headers=auth(token))
    assert r.status_code == 200
    res = r.json()["results"]
    assert [x["status"] for x in res] == ["invalid", "invalid", "review"]
    assert [x["id"] for x in res] == [None, "long", "ok"]
    assert "synced" not in r.json()["say"] and r.json()["say"].startswith("Recorded")
    assert [r[0] for r in conn.execute("SELECT client_id FROM entries")] == ["ok"]


def test_all_invalid_batch_say(client, conn, token):
    r = client.post("/api/voice", json={"items": [{}, {"id": "x"}]}, headers=auth(token))
    assert r.status_code == 200 and r.json()["say"] == "Some entries could not be read"
    repo.set_setting(conn, "lang", "zh")
    r = client.post("/api/voice", json={"items": [{}]}, headers=auth(token))
    assert r.json()["say"] == "有记录无法识别"


def test_boundary_coords_ok(client, token):
    r = client.post("/api/voice", json={"items": [it("g", lat=90, lon=-180)]}, headers=auth(token))
    assert r.status_code == 200


def test_body_too_large(client, token):
    r = client.post("/api/voice", content=b"x" * (300 * 1024), headers=auth(token))
    assert r.status_code == 413
    r = client.post("/api/voice", content=b"x" * (300 * 1024))
    assert r.status_code == 401


def test_streamed_body_cap_without_content_length(client, token):
    def gen():
        for _ in range(30):
            yield b"x" * 10240
    r = client.post("/api/voice", content=gen(), headers=auth(token))
    assert r.status_code == 413


def test_all_duplicate_batch_has_nonempty_say(client, token):
    client.post("/api/voice", json={"items": [ITEM_A]}, headers=auth(token))
    r = client.post("/api/voice", json={"items": [ITEM_A]}, headers=auth(token))
    assert r.status_code == 200 and r.json()["say"] == "Already synced"
    assert r.json()["results"][0]["status"] == "duplicate"
