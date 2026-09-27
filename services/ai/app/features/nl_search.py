"""NL search: free text → validated SearchFilters (FR-3, docs/design.md §4.3)."""

from app import guardrails
from app.features import rules
from app.features.schemas import SUPPORTED_CITIES, SearchFilters
from app.llm import get_llm
from app.llm.base import CallContext
from app.prompts.loader import render

MAX_QUERY_CHARS = 300
PROTECTED_DROPPED = "Some preferences can't be used as search filters."


def post_process(f: SearchFilters) -> SearchFilters:
    """Deterministic clean-up of model output — never trust structure alone."""
    f.city = rules.normalise_city(f.city) or f.city
    if f.locality and not f.city:
        f.city = rules.city_for_locality(f.locality)
    if f.bedrooms_min is not None and f.bedrooms_max is not None and f.bedrooms_min > f.bedrooms_max:
        f.bedrooms_min, f.bedrooms_max = f.bedrooms_max, f.bedrooms_min
    if f.price_min_inr and f.price_max_inr and f.price_min_inr > f.price_max_inr:
        f.price_min_inr, f.price_max_inr = f.price_max_inr, f.price_min_inr
    for field in ("bedrooms_min", "bedrooms_max", "price_min_inr", "price_max_inr"):
        if (value := getattr(f, field)) is not None and value < 0:
            setattr(f, field, None)
    kept = [p for p in f.soft_preferences if not guardrails.mentions_protected(p)]
    if len(kept) != len(f.soft_preferences) and PROTECTED_DROPPED not in f.assumptions:
        f.assumptions.append(PROTECTED_DROPPED)
    f.soft_preferences = kept[:5]
    f.assumptions = f.assumptions[:4]
    return f


async def parse(query: str, user_id: str | None = None) -> tuple[SearchFilters, str]:
    clean = guardrails.redact_pii(guardrails.sanitize(query, MAX_QUERY_CHARS))
    prompt = render("nl_search", query=clean, supported_cities=SUPPORTED_CITIES)
    result = await get_llm().parse(prompt, SearchFilters, CallContext(feature="nl_search", user_id=user_id))
    return post_process(result.output), result.request_id
