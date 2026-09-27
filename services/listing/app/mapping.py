"""Conversions between the Listing aggregate and its API / event / AI representations."""

from app.models import Listing
from app.money import format_inr, minor_to_rupees, money_out
from app.schemas import DocumentOut, ImageOut, ListingOut, ListingSummary

MEDIA_PREFIX = "/api/v1/media/"


def media_url(key: str) -> str:
    return MEDIA_PREFIX + key


def to_out(listing: Listing) -> ListingOut:
    return ListingOut(
        **{c: getattr(listing, c) for c in ListingOut.model_fields if c not in {"price", "deposit", "maintenance", "images"}},
        price=money_out(listing.price_minor, listing.currency),
        deposit=money_out(listing.deposit_minor, listing.currency),
        maintenance=money_out(listing.maintenance_minor, listing.currency),
        images=[
            ImageOut(id=i.id, url=media_url(i.storage_key), thumb_url=media_url(i.thumb_key), caption=i.caption, position=i.position)
            for i in listing.images
        ],
    )


def to_summary(listing: Listing) -> ListingSummary:
    return ListingSummary(
        id=listing.id,
        status=listing.status,
        title=listing.title,
        price=money_out(listing.price_minor, listing.currency),
        bedrooms=listing.bedrooms,
        locality=listing.locality,
        city=listing.city,
        thumbnail_url=media_url(listing.images[0].thumb_key) if listing.images else None,
        documents_count=len(listing.documents),
        updated_at=listing.updated_at,
    )


def to_documents(listing: Listing) -> list[DocumentOut]:
    return [
        DocumentOut(id=d.id, filename=d.filename, kind=d.kind, status=d.status, error=d.error, created_at=d.created_at)
        for d in listing.documents
    ]


def to_snapshot(listing: Listing) -> dict:
    """Event payload consumed by the search service read model. Contains no agent PII."""
    return {
        "id": str(listing.id),
        "status": listing.status,
        "listing_type": listing.listing_type,
        "property_type": listing.property_type,
        "title": listing.title,
        "description": listing.description or "",
        "price_minor": listing.price_minor,
        "currency": listing.currency,
        "bedrooms": listing.bedrooms,
        "bathrooms": listing.bathrooms,
        "carpet_area_sqft": listing.carpet_area_sqft,
        "furnishing": listing.furnishing,
        "pet_policy": listing.pet_policy,
        "amenities": list(listing.amenities or []),
        "locality": listing.locality,
        "city": listing.city,
        "lat": listing.lat,
        "lng": listing.lng,
        "thumbnail_key": listing.images[0].thumb_key if listing.images else None,
        "published_at": listing.published_at.isoformat() if listing.published_at else None,
    }


def to_facts(listing: Listing) -> list[dict]:
    """Citable fact sheet (S1..Sn) for AI features. Excludes agent contact and street address."""
    rent = listing.listing_type == "rent"
    rows: list[tuple[str, object]] = [
        ("Listing type", "For rent" if rent else "For sale"),
        ("Property type", listing.property_type.replace("_", " ")),
        ("Monthly rent" if rent else "Price", format_inr(minor_to_rupees(listing.price_minor))),
        ("Security deposit", listing.deposit_minor and format_inr(minor_to_rupees(listing.deposit_minor))),
        ("Maintenance per month", listing.maintenance_minor and format_inr(minor_to_rupees(listing.maintenance_minor))),
        ("Bedrooms (BHK)", listing.bedrooms),
        ("Bathrooms", listing.bathrooms),
        ("Balconies", listing.balconies),
        ("Carpet area", listing.carpet_area_sqft and f"{listing.carpet_area_sqft} sq ft"),
        ("Built-up area", listing.builtup_area_sqft and f"{listing.builtup_area_sqft} sq ft"),
        ("Floor", listing.floor is not None and listing.total_floors and f"{listing.floor} of {listing.total_floors}"),
        ("Facing", listing.facing and listing.facing.replace("_", "-")),
        ("Furnishing", listing.furnishing and listing.furnishing.replace("_", " ")),
        ("Covered parking", listing.parking_covered or None),
        ("Open parking", listing.parking_open or None),
        ("Pets", {"allowed": "Allowed", "not_allowed": "Not allowed"}.get(listing.pet_policy)),
        ("Possession", listing.possession and listing.possession.replace("_", " ")),
        ("Amenities", ", ".join(a.replace("_", " ") for a in listing.amenities) if listing.amenities else None),
        ("Locality", listing.locality),
        ("City", listing.city),
        ("RERA registration", listing.rera_id),
    ]
    facts = [(label, value) for label, value in rows if value not in (None, False, "", 0)]
    return [{"id": f"S{i}", "label": label, "value": str(value)} for i, (label, value) in enumerate(facts, start=1)]
