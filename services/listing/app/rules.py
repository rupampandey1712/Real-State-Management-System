"""Listing business rules that are pure functions of the aggregate (unit-tested in tests/test_rules.py)."""

from datetime import date

from app.models import Listing

# Agents may edit and publish these; the other states are set by the system or an admin.
AGENT_STATUSES = {"draft", "published", "unpublished"}
NO_LIVING_SPACE = {"plot"}  # plots have no carpet area, furnishing or bedrooms to describe


def publish_problems(listing: Listing) -> list[dict[str, str]]:
    """Fields that must be filled before a listing can go live (FR-1 AC: block publishing and highlight
    each missing field). Returns `{field, issue}` items in the error-envelope `details` format."""
    problems: list[dict[str, str]] = []

    def need(field: str, issue: str = "required") -> None:
        problems.append({"field": field, "issue": issue})

    description = (listing.description or "").strip()
    if not description:
        need("description")
    elif len(description) < 50:
        need("description", "too_short_min_50_characters")
    if not listing.pincode:
        need("pincode")
    if listing.property_type not in NO_LIVING_SPACE:
        if not listing.carpet_area_sqft:
            need("carpet_area_sqft")
        if not listing.bathrooms:
            need("bathrooms")
        if not listing.furnishing:
            need("furnishing")
    elif not (listing.builtup_area_sqft or listing.carpet_area_sqft):
        need("builtup_area_sqft")
    if listing.listing_type == "rent" and listing.deposit_minor is None:
        need("deposit_inr")
    if not listing.possession:
        need("possession")
    if rera_required(listing) and not listing.rera_id:
        need("rera_id", "required_for_under_construction_projects")
    if (listing.lat is None) != (listing.lng is None):
        need("lat", "set_both_latitude_and_longitude")
    return problems


def rera_required(listing: Listing) -> bool:
    """RERA (FR-1.4, requirements §7): projects sold before completion must be registered. A home for sale
    that is under construction, or whose possession date is in the future, is such a project."""
    if listing.listing_type != "sale" or not listing.possession or listing.possession == "ready_to_move":
        return False
    if listing.possession == "under_construction":
        return True
    return listing.possession > date.today().isoformat()[: len(listing.possession)]  # ISO dates compare as text


def duplicate_title(title: str) -> str:
    return f"Copy of {title}"[:120]
