import pytest
from fastapi.testclient import TestClient

from helpers import NoLLM, FakeLLM
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


def test_records_batch(client, token):
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
    {"items": []}, {"items": [ITEM] * 201}, {}, {"items": [{"id": "x"}]},
    {"items": [it("g", lat=91, lon=0)]}, {"items": [it("g", lat=0, lon=181)]},
    {"items": [it("g", lat=-90.1, lon=0)]},
])
def test_bad_body_422(client, token, body):
    assert client.post("/api/voice", json=body, headers=auth(token)).status_code == 422


def test_nan_inf_422(client, token):
    for v in ("NaN", "Infinity"):
        raw = ('{"items":[{"id":"g","text":"1","captured_at":"%s","lat":%s,"lon":0}]}' % (T, v))
        r = client.post("/api/voice", content=raw, headers={**auth(token), "content-type": "application/json"})
        assert r.status_code == 422


def test_boundary_coords_ok(client, token):
    r = client.post("/api/voice", json={"items": [it("g", lat=90, lon=-180)]}, headers=auth(token))
    assert r.status_code == 200


def test_body_too_large(client, token):
    r = client.post("/api/voice", content=b"x" * (300 * 1024), headers=auth(token))
    assert r.status_code == 413
    r = client.post("/api/voice", content=b"x" * (300 * 1024))
    assert r.status_code == 401
