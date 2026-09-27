from app.features import rules
from app.features.nl_search import PROTECTED_DROPPED, post_process
from app.features.schemas import SearchFilters


def test_bhk_budget_city():
    f = rules.parse_query("2bhk under 80L in pune")
    assert (f.city, f.bedrooms_min, f.bedrooms_max, f.price_max_inr, f.listing_type) == ("Pune", 2, 2, 8_000_000, "sale")


def test_rent_locality_implies_city():
    f = rules.parse_query("furnished 1 bhk for rent in koramangala below 25k, pets ok")
    assert f.listing_type == "rent"
    assert (f.city, f.locality) == ("Bengaluru", "Koramangala")
    assert f.price_max_inr == 25_000
    assert f.furnishing == "fully_furnished"
    assert f.pet_policy == "allowed"


def test_range_in_crore_and_amenities():
    f = rules.parse_query("villa with pool and gym, 3 to 4 bedrooms, budget 3-4 crore")
    assert (f.bedrooms_min, f.bedrooms_max) == (3, 4)
    assert (f.price_min_inr, f.price_max_inr) == (30_000_000, 40_000_000)
    assert f.property_type == "villa"
    assert f.amenities == ["gym", "swimming_pool"]


def test_near_and_soft_preferences():
    f = rules.parse_query("2 bhk near metro in pune, quiet with natural light")
    assert f.near == ["metro"]
    assert "quiet" in f.soft_preferences and "natural light" in f.soft_preferences


def test_non_property_query():
    assert rules.parse_query("hi there, how are you?").is_property_query is False


def test_post_process_drops_protected_preferences_and_fixes_ranges():
    f = SearchFilters.empty(
        locality="Koramangala", bedrooms_min=3, bedrooms_max=2, price_min_inr=9_000_000, price_max_inr=5_000_000,
        soft_preferences=["vegetarian society", "quiet"],
    )
    out = post_process(f)
    assert out.city == "Bengaluru"
    assert (out.bedrooms_min, out.bedrooms_max) == (2, 3)
    assert (out.price_min_inr, out.price_max_inr) == (5_000_000, 9_000_000)
    assert out.soft_preferences == ["quiet"]
    assert PROTECTED_DROPPED in out.assumptions
