import io
import uuid

import pytest
from PIL import Image

from app.images import process_image
from app.models import Listing
from app.rules import duplicate_title, publish_problems, rera_required
from estate_common.errors import ValidationFailed


def complete_listing(**overrides) -> Listing:
    values = dict(
        agent_id=uuid.uuid4(), status="draft", listing_type="sale", property_type="apartment",
        title="2 BHK apartment in Kharadi", description="A bright two bedroom home close to the IT park, with a balcony.",
        price_minor=80_00_000_00, bedrooms=2, bathrooms=2, carpet_area_sqft=900, furnishing="semi_furnished",
        pincode="411014", possession="ready_to_move", address_line="Sample Residency", locality="Kharadi", city="Pune",
    )
    return Listing(**(values | overrides))


def fields(problems: list[dict]) -> set[str]:
    return {p["field"] for p in problems}


def test_complete_listing_can_publish():
    assert publish_problems(complete_listing()) == []


def test_each_missing_field_is_reported():
    listing = complete_listing(description=None, pincode=None, carpet_area_sqft=None, furnishing=None, possession=None)
    assert fields(publish_problems(listing)) == {"description", "pincode", "carpet_area_sqft", "furnishing", "possession"}


def test_short_description_is_flagged():
    [problem] = publish_problems(complete_listing(description="Nice flat."))
    assert problem == {"field": "description", "issue": "too_short_min_50_characters"}


def test_rent_needs_deposit():
    assert fields(publish_problems(complete_listing(listing_type="rent"))) == {"deposit_inr"}


def test_plot_needs_area_but_not_furnishing():
    plot = complete_listing(property_type="plot", carpet_area_sqft=None, bathrooms=None, furnishing=None)
    assert fields(publish_problems(plot)) == {"builtup_area_sqft"}


def test_half_a_map_pin_is_rejected():
    assert fields(publish_problems(complete_listing(lat=18.55))) == {"lat"}


@pytest.mark.parametrize(("listing_type", "possession", "required"), [
    ("sale", "under_construction", True),
    ("sale", "2099-06", True),
    ("sale", "2001-01-01", False),
    ("sale", "ready_to_move", False),
    ("rent", "under_construction", False),
])
def test_rera_required_for_projects_under_construction(listing_type, possession, required):
    listing = complete_listing(listing_type=listing_type, possession=possession, deposit_minor=0)
    assert rera_required(listing) is required
    assert ("rera_id" in fields(publish_problems(listing))) is required


def test_duplicate_title_fits_column():
    assert duplicate_title("x" * 120) == ("Copy of " + "x" * 120)[:120]


def _image_bytes(fmt: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (2000, 1000), "white").save(buffer, format=fmt)
    return buffer.getvalue()


def test_png_becomes_two_webp_sizes():
    display, thumb = process_image(_image_bytes("PNG"))
    assert Image.open(io.BytesIO(display)).size == (1600, 800)
    assert Image.open(io.BytesIO(thumb)).size == (400, 200)


def test_gif_is_rejected():
    with pytest.raises(ValidationFailed):
        process_image(_image_bytes("GIF"))


def test_heic_is_accepted():
    from pillow_heif import from_pillow

    buffer = io.BytesIO()
    from_pillow(Image.new("RGB", (800, 600), "white")).save(buffer, format="HEIF")
    display, _thumb = process_image(buffer.getvalue())
    assert Image.open(io.BytesIO(display)).format == "WEBP"
