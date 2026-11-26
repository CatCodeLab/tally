"""Local place learning: GPS points resolve to shops, entirely in the local DB."""
import math
from dataclasses import dataclass

RADIUS_M = 50.0


@dataclass
class PlaceMatch:
    place_id: int | None
    shop: str | None
    ambiguous: bool = False


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def add_place(conn, shop: str | None, lat: float, lon: float, visits: int = 1,
              commit: bool = True) -> int:
    cur = conn.execute("INSERT INTO places(shop, lat, lon, visits) VALUES (?, ?, ?, ?)",
                       (shop, lat, lon, visits))
    if commit:
        conn.commit()
    return cur.lastrowid


def _nearby(conn, lat: float, lon: float) -> list[tuple[float, dict]]:
    rows = conn.execute("SELECT id, shop, lat, lon, visits FROM places "
                        "WHERE lat IS NOT NULL AND lon IS NOT NULL ORDER BY id").fetchall()
    out = []
    for r in rows:
        d = haversine_m(lat, lon, r["lat"], r["lon"])
        if d <= RADIUS_M:
            out.append((d, dict(r)))
    out.sort(key=lambda t: t[0])
    return out


def _visit(conn, p: dict, lat: float, lon: float) -> None:
    n = p["visits"]
    conn.execute("UPDATE places SET visits = ?, lat = ?, lon = ? WHERE id = ?",
                 (n + 1, (p["lat"] * n + lat) / (n + 1), (p["lon"] * n + lon) / (n + 1),
                  p["id"]))


def resolve_place(conn, lat: float | None, lon: float | None, spoken_shop: str | None,
                  commit: bool = True) -> PlaceMatch:
    spoken = (spoken_shop or "").strip() or None
    if lat is None or lon is None:
        return PlaceMatch(None, spoken, False)
    near = [p for _, p in _nearby(conn, lat, lon)]
    if spoken:
        same = [p for p in near if p["shop"] == spoken]
        unnamed = [p for p in near if p["shop"] is None]
        if same:
            pid = same[0]["id"]
            _visit(conn, same[0], lat, lon)
        elif unnamed:
            pid = unnamed[0]["id"]
            conn.execute("UPDATE places SET shop = ? WHERE id = ?", (spoken, pid))
            _visit(conn, unnamed[0], lat, lon)
        else:
            pid = add_place(conn, spoken, lat, lon, commit=False)
        match = PlaceMatch(pid, spoken, False)
    else:
        named = [p for p in near if p["shop"]]
        if named:
            best = max(named, key=lambda p: p["visits"])  # stable: nearest wins ties
            _visit(conn, best, lat, lon)
            match = PlaceMatch(best["id"], best["shop"],
                               len({p["shop"] for p in named}) > 1)
        elif near:
            _visit(conn, near[0], lat, lon)
            match = PlaceMatch(near[0]["id"], None, False)
        else:
            match = PlaceMatch(add_place(conn, None, lat, lon, commit=False), None, False)
    if commit:
        conn.commit()
    return match
