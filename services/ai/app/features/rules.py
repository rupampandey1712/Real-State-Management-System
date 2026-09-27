"""Rule-based NL query parser. Used by FakeLLMClient (offline dev), as a comparison baseline in
evals, and for gazetteer normalisation of LLM output."""

import re

from app.features.schemas import SearchFilters

CITY_ALIASES = {
    "pune": "Pune", "poona": "Pune",
    "bengaluru": "Bengaluru", "bangalore": "Bengaluru", "blr": "Bengaluru",
    "mumbai": "Mumbai", "bombay": "Mumbai", "navi mumbai": "Mumbai", "thane": "Mumbai",
}
LOCALITY_CITY = {
    "kharadi": "Pune", "baner": "Pune", "hinjewadi": "Pune", "wakad": "Pune", "viman nagar": "Pune", "kothrud": "Pune",
    "koramangala": "Bengaluru", "indiranagar": "Bengaluru", "whitefield": "Bengaluru", "hsr layout": "Bengaluru",
    "hebbal": "Bengaluru", "andheri": "Mumbai", "andheri west": "Mumbai", "powai": "Mumbai",
    "bandra": "Mumbai", "bandra west": "Mumbai", "thane west": "Mumbai", "goregaon": "Mumbai", "goregaon east": "Mumbai",
}
AMENITY_SYNONYMS = {
    "lift": "lift", "elevator": "lift", "gym": "gym", "pool": "swimming_pool", "swimming": "swimming_pool",
    "power backup": "power_backup", "generator": "power_backup", "security": "security_24x7",
    "clubhouse": "club_house", "club house": "club_house", "play area": "children_play_area",
    "gated": "gated", "park": "park", "ev charging": "ev_charging", "intercom": "intercom",
}
NEAR_WORDS = {
    "metro": "metro", "school": "school", "hospital": "hospital", "it park": "it_park", "tech park": "it_park",
    "mall": "mall", "railway": "railway_station", "station": "railway_station", "airport": "airport",
}
SOFT_WORDS = ["quiet", "peaceful", "natural light", "good light", "sunlight", "view", "green", "spacious",
              "ventilation", "family friendly", "not ground floor", "high floor", "low floor"]
PROPERTY_WORDS = re.compile(r"\b(bhk|rk|flat|apartment|house|villa|plot|home|rent|buy|property|studio|bedroom|pg)\b", re.I)

AMOUNT = r"(\d+(?:\.\d+)?)\s*(cr|crore|crores|l|lac|lacs|lakh|lakhs|k|thousand)?\b"
MAX_RE = re.compile(r"\b(?:under|below|within|max|upto|up to|less than|budget(?: of)?)\s*(?:rs\.?|₹|inr)?\s*" + AMOUNT, re.I)
MIN_RE = re.compile(r"\b(?:above|over|min|minimum|more than|at least)\s*(?:rs\.?|₹|inr)?\s*" + AMOUNT, re.I)
AROUND_RE = re.compile(r"\b(?:around|about|approx|approximately|~)\s*(?:rs\.?|₹|inr)?\s*" + AMOUNT, re.I)
# A range needs a unit ("3-4 crore"), otherwise "3 to 4 bedrooms" would read as a price.
RANGE_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*(cr|crore|crores|l|lac|lacs|lakh|lakhs|k|thousand)\b", re.I)
BHK_RE = re.compile(r"\b(\d)\s*(?:(?:-|to)\s*(\d)\s*)?(?:bhk|bed(?:room)?s?|br)\b", re.I)


def to_rupees(number: str, unit: str | None) -> int:
    value = float(number)
    unit = (unit or "").lower()
    if unit in {"cr", "crore", "crores"}:
        value *= 10_000_000
    elif unit in {"l", "lac", "lacs", "lakh", "lakhs"}:
        value *= 100_000
    elif unit in {"k", "thousand"}:
        value *= 1_000
    return round(value)


def normalise_city(value: str | None) -> str | None:
    return CITY_ALIASES.get(value.lower().strip()) if value else None


def city_for_locality(locality: str | None) -> str | None:
    return LOCALITY_CITY.get(locality.lower().strip()) if locality else None


def parse_query(query: str) -> SearchFilters:
    q = query.lower()
    f = SearchFilters.empty()
    if not PROPERTY_WORDS.search(q) and not BHK_RE.search(q):
        return SearchFilters.empty(is_property_query=False)

    if m := BHK_RE.search(q):
        f.bedrooms_min = int(m.group(1))
        f.bedrooms_max = int(m.group(2) or m.group(1))
    elif re.search(r"\b(1\s*rk|studio)\b", q):
        f.bedrooms_min = f.bedrooms_max = 0

    if m := RANGE_RE.search(q):
        unit = m.group(3)
        f.price_min_inr, f.price_max_inr = to_rupees(m.group(1), unit), to_rupees(m.group(2), unit)
    elif m := AROUND_RE.search(q):
        centre = to_rupees(m.group(1), m.group(2))
        f.price_min_inr, f.price_max_inr = round(centre * 0.9), round(centre * 1.1)
    else:
        if m := MAX_RE.search(q):
            f.price_max_inr = to_rupees(m.group(1), m.group(2))
        if m := MIN_RE.search(q):
            f.price_min_inr = to_rupees(m.group(1), m.group(2))

    if re.search(r"\b(rent|rental|lease|per month|pm|pg)\b", q):
        f.listing_type = "rent"
    elif re.search(r"\b(buy|purchase|resale|sale|investment)\b", q):
        f.listing_type = "sale"
    elif f.price_max_inr and f.price_max_inr >= 2_000_000:
        f.listing_type = "sale"
        f.assumptions.append("Assumed you want to buy, based on the budget.")

    for alias, city in CITY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", q):
            f.city = city
            break
    for locality in sorted(LOCALITY_CITY, key=len, reverse=True):
        if re.search(rf"\b{re.escape(locality)}\b", q):
            f.locality = locality.title()
            f.city = f.city or LOCALITY_CITY[locality]
            break

    for word, prop in {"villa": "villa", "independent house": "independent_house", "plot": "plot",
                       "office": "commercial", "shop": "commercial", "flat": "apartment", "apartment": "apartment"}.items():
        if word in q:
            f.property_type = prop
            break
    if "semi furnished" in q or "semi-furnished" in q:
        f.furnishing = "semi_furnished"
    elif "unfurnished" in q:
        f.furnishing = "unfurnished"
    elif "furnished" in q:
        f.furnishing = "fully_furnished"
    if re.search(r"\b(pet|pets|dog|cat)\b", q) and not re.search(r"\bno pets?\b", q):
        f.pet_policy = "allowed"

    f.amenities = sorted({a for word, a in AMENITY_SYNONYMS.items() if re.search(rf"\b{re.escape(word)}\b", q)})
    f.near = sorted({n for word, n in NEAR_WORDS.items() if re.search(rf"\b(near|close to|walking distance to|next to)\b.*\b{word}", q)})
    f.soft_preferences = [w for w in SOFT_WORDS if w in q]
    if f.city is None:
        f.assumptions.append("No city given, so searching all cities.")
    return f
