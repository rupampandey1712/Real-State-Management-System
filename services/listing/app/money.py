"""Money helpers. Amounts are stored as integer paise (minor units). Never floats.

1 lakh = 1,00,000 INR · 1 crore = 1,00,00,000 INR (docs/glossary.md).
"""

import re

LAKH = 100_000
CRORE = 10_000_000
PAISE_PER_RUPEE = 100

_AMOUNT = re.compile(r"^\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)\s*(cr|crore|crores|l|lac|lacs|lakh|lakhs|k|thousand)?\s*$", re.I)


def rupees_to_minor(rupees: int) -> int:
    return rupees * PAISE_PER_RUPEE


def minor_to_rupees(minor: int) -> int:
    return minor // PAISE_PER_RUPEE


def parse_amount(text: str) -> int:
    """'80L' → 8000000, '1.2 cr' → 12000000, '25k' → 25000, '₹45,00,000' → 4500000."""
    match = _AMOUNT.match(text)
    if not match:
        raise ValueError(f"Unrecognised amount: {text!r}")
    number = float(match.group(1).replace(",", ""))
    unit = (match.group(2) or "").lower()
    if unit in {"cr", "crore", "crores"}:
        number *= CRORE
    elif unit in {"l", "lac", "lacs", "lakh", "lakhs"}:
        number *= LAKH
    elif unit in {"k", "thousand"}:
        number *= 1_000
    return round(number)


def _indian_grouping(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def format_inr(rupees: int) -> str:
    """Display format: ≥ 1 crore → '₹1.2 Cr', ≥ 1 lakh → '₹78 L', else '₹25,000'."""
    if rupees >= CRORE:
        return f"₹{rupees / CRORE:.2f}".rstrip("0").rstrip(".") + " Cr"
    if rupees >= LAKH:
        return f"₹{rupees / LAKH:.2f}".rstrip("0").rstrip(".") + " L"
    return f"₹{_indian_grouping(rupees)}"


def money_out(minor: int | None, currency: str = "INR") -> dict | None:
    if minor is None:
        return None
    return {"amount_minor": minor, "currency": currency, "display": format_inr(minor_to_rupees(minor))}
