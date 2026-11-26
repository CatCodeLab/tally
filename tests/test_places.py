from tally.places import haversine_m, resolve_place
from helpers import add_place


def test_haversine():
    assert 44 < haversine_m(40.7128, -74.0060, 40.7132, -74.0060) < 45


def test_no_coords_keeps_spoken(conn):
    m = resolve_place(conn, None, None, "X")
    assert (m.place_id, m.shop, m.ambiguous) == (None, "X", False)


def test_spoken_matches_and_moves_mean(conn):
    pid = add_place(conn, "A", 10.0, 10.0, visits=1)
    m = resolve_place(conn, 10.0002, 10.0, "A")
    assert m.place_id == pid
    r = conn.execute("SELECT visits, lat FROM places WHERE id=?", (pid,)).fetchone()
    assert r["visits"] == 2 and abs(r["lat"] - 10.0001) < 1e-9


def test_spoken_names_unnamed_place(conn):
    pid = add_place(conn, None, 10.0, 10.0)
    assert resolve_place(conn, 10.0, 10.0, "B").place_id == pid
    assert conn.execute("SELECT shop FROM places WHERE id=?", (pid,)).fetchone()[0] == "B"


def test_spoken_creates_place_when_other_shop_nearby(conn):
    pid = add_place(conn, "A", 10.0, 10.0)
    m = resolve_place(conn, 10.0, 10.0, "C")
    assert m.place_id != pid and m.shop == "C"


def test_far_place_ignored(conn):
    add_place(conn, "A", 10.0, 10.0)
    m = resolve_place(conn, 10.001, 10.0, None)  # ~111 m
    assert m.shop is None
    assert conn.execute("SELECT COUNT(*) FROM places").fetchone()[0] == 2


def test_unspoken_ambiguous_picks_most_visited(conn):
    add_place(conn, "A", 10.0, 10.0, visits=2)
    b = add_place(conn, "B", 10.0001, 10.0, visits=5)
    m = resolve_place(conn, 10.0, 10.0, None)
    assert (m.place_id, m.shop, m.ambiguous) == (b, "B", True)
    assert conn.execute("SELECT visits FROM places WHERE id=?", (b,)).fetchone()[0] == 6
