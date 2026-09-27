import pytest

from app.money import format_inr, parse_amount, rupees_to_minor


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("80L", 8_000_000),
        ("80 lakh", 8_000_000),
        ("1.2 cr", 12_000_000),
        ("1.2 Crore", 12_000_000),
        ("25k", 25_000),
        ("₹45,00,000", 4_500_000),
        ("Rs. 35000", 35_000),
        ("95 lacs", 9_500_000),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_parse_amount_rejects_garbage():
    with pytest.raises(ValueError):
        parse_amount("cheap")


@pytest.mark.parametrize(
    ("rupees", "expected"),
    [
        (7_800_000, "₹78 L"),
        (12_000_000, "₹1.2 Cr"),
        (12_500_000, "₹1.25 Cr"),
        (25_000, "₹25,000"),
        (150_000, "₹1.5 L"),
        (999, "₹999"),
    ],
)
def test_format_inr(rupees, expected):
    assert format_inr(rupees) == expected


def test_minor_units_are_integers():
    assert rupees_to_minor(8_000_000) == 800_000_000
