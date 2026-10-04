"""Points of interest for `near` preferences ("near a metro") — docs/design.md §4.3.

Source: app/data/pois.csv, a small hand-checked list derived from OpenStreetMap (© OpenStreetMap
contributors, ODbL) for the launch cities. Coordinates are approximate (±200 m), which is fine for a
1.5 km "near" radius. It is small enough to keep in memory, so scoring needs no extra query; replace it
with an OSM extract job if it grows past a few thousand rows.

near_score: distance to the nearest POI of a requested type — ≤ 1.5 km scores 1.0, falling linearly
to 0 at 5 km. With several types requested, the score is the average.
"""

import csv
import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data" / "pois.csv"
FULL_SCORE_KM = 1.5
ZERO_SCORE_KM = 5.0


@dataclass(frozen=True)
class POI:
    type: str
    name: str
    city: str
    lat: float
    lng: float


@lru_cache
def load_pois() -> tuple[POI, ...]:
    with DATA.open(encoding="utf-8") as handle:
        return tuple(POI(r["type"], r["name"], r["city"], float(r["lat"]), float(r["lng"])) for r in csv.DictReader(handle))


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def nearest(lat: float, lng: float, poi_type: str) -> tuple[POI, float] | None:
    candidates = [(p, haversine_km(lat, lng, p.lat, p.lng)) for p in load_pois() if p.type == poi_type]
    return min(candidates, key=lambda c: c[1]) if candidates else None


def distance_score(km: float) -> float:
    if km <= FULL_SCORE_KM:
        return 1.0
    if km >= ZERO_SCORE_KM:
        return 0.0
    return round(1 - (km - FULL_SCORE_KM) / (ZERO_SCORE_KM - FULL_SCORE_KM), 4)


def near_score(lat: float | None, lng: float | None, types: Sequence[str]) -> tuple[float, list[str]]:
    """(score, reasons). No `near` request → 1.0 for everyone (no effect on order); no map pin → 0."""
    if not types:
        return 1.0, []
    if lat is None or lng is None:
        return 0.0, []
    scores, reasons = [], []
    for poi_type in types:
        found = nearest(lat, lng, poi_type)
        if found is None:
            scores.append(0.0)
            continue
        poi, km = found
        scores.append(distance_score(km))
        if km <= ZERO_SCORE_KM:
            reasons.append(f"{km:.1f} km to {poi.name}" if km >= 0.1 else f"Next to {poi.name}")
    return round(sum(scores) / len(scores), 4), reasons
