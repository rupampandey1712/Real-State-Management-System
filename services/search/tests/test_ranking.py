import pytest

from app.pois import distance_score, haversine_km, load_pois, near_score
from app.ranking import parse_bbox


def test_pois_cover_every_launch_city():
    cities = {p.city for p in load_pois() if p.type == "metro"}
    assert cities == {"Pune", "Bengaluru", "Mumbai"}


def test_haversine_is_close_to_known_distance():
    # Pune Junction → Shivajinagar station is roughly 2.7 km apart
    assert haversine_km(18.5289, 73.8743, 18.5325, 73.8497) == pytest.approx(2.6, abs=0.3)


@pytest.mark.parametrize(("km", "score"), [(0.2, 1.0), (1.5, 1.0), (3.25, 0.5), (5.0, 0.0), (9.0, 0.0)])
def test_distance_score_decays_linearly(km, score):
    assert distance_score(km) == pytest.approx(score)


def test_near_score_rewards_homes_next_to_a_metro():
    close, reasons = near_score(12.9790, 77.6390, ["metro"])  # by Indiranagar metro
    far, _ = near_score(13.1000, 77.4000, ["metro"])  # outskirts
    assert close == 1.0 and reasons and "Indiranagar" in reasons[0]
    assert far == 0.0


def test_near_score_is_neutral_without_a_near_request():
    assert near_score(None, None, []) == (1.0, [])


def test_near_score_is_zero_without_a_map_pin():
    assert near_score(None, None, ["metro"]) == (0.0, [])


@pytest.mark.parametrize(("raw", "expected"), [
    ("73.7,18.4,74.0,18.7", (73.7, 18.4, 74.0, 18.7)),
    (None, None),
    ("", None),
    ("a,b,c,d", None),
    ("74.0,18.4,73.7,18.7", None),  # min > max
    ("73.7,18.4,74.0", None),
])
def test_parse_bbox(raw, expected):
    assert parse_bbox(raw) == expected
