"""Hybrid search: hard SQL filters + vector similarity + filter fit + freshness (docs/design.md §4.3)."""

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Select, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import SearchListing

PRICE_TOLERANCE = 1.05  # include up to 5% over budget, penalised in scoring


@dataclass
class Filters:
    city: str | None = None
    locality: str | None = None
    listing_type: str | None = None
    property_type: str | None = None
    bedrooms_min: int | None = None
    bedrooms_max: int | None = None
    price_min_minor: int | None = None
    price_max_minor: int | None = None
    furnishing: str | None = None
    pet_policy: str | None = None
    amenities: list[str] = field(default_factory=list)


def apply_filters(stmt: Select, f: Filters, *, tolerant_price: bool = False) -> Select:
    stmt = stmt.where(SearchListing.listing_type == f.listing_type) if f.listing_type else stmt
    stmt = stmt.where(SearchListing.city == f.city) if f.city else stmt
    stmt = stmt.where(SearchListing.locality.ilike(f"%{f.locality}%")) if f.locality else stmt
    stmt = stmt.where(SearchListing.property_type == f.property_type) if f.property_type else stmt
    stmt = stmt.where(SearchListing.bedrooms >= f.bedrooms_min) if f.bedrooms_min is not None else stmt
    stmt = stmt.where(SearchListing.bedrooms <= f.bedrooms_max) if f.bedrooms_max is not None else stmt
    stmt = stmt.where(SearchListing.price_minor >= f.price_min_minor) if f.price_min_minor else stmt
    if f.price_max_minor:
        limit = int(f.price_max_minor * PRICE_TOLERANCE) if tolerant_price else f.price_max_minor
        stmt = stmt.where(SearchListing.price_minor <= limit)
    stmt = stmt.where(SearchListing.furnishing == f.furnishing) if f.furnishing else stmt
    stmt = stmt.where(SearchListing.pet_policy == f.pet_policy) if f.pet_policy else stmt
    stmt = stmt.where(SearchListing.amenities.contains(f.amenities)) if f.amenities else stmt
    return stmt


def _filter_fit(row: SearchListing, f: Filters) -> tuple[float, list[str]]:
    score, reasons = 1.0, []
    if f.price_max_minor:
        if row.price_minor <= f.price_max_minor:
            reasons.append("Within budget")
        else:
            score -= 0.5 * (row.price_minor / f.price_max_minor - 1) / (PRICE_TOLERANCE - 1)
            reasons.append("Slightly over budget")
    if f.bedrooms_min is not None and f.bedrooms_min == f.bedrooms_max:
        reasons.append(f"{row.bedrooms} BHK")
    if f.locality and f.locality.lower() in row.locality.lower():
        reasons.append(f"In {row.locality}")
    if f.amenities:
        reasons.append("Has " + ", ".join(a.replace("_", " ") for a in f.amenities[:3]))
    return max(score, 0.0), reasons


def _freshness(published_at: datetime | None) -> float:
    if published_at is None:
        return 0.0
    days = (datetime.now(UTC) - published_at).days
    return math.exp(-days / 30)


async def hybrid_search(
    session: AsyncSession, f: Filters, query_vector: list[float] | None, fts_query: str | None, offset: int, limit: int
) -> tuple[list[tuple[SearchListing, float, list[str]]], bool]:
    """Returns (rows with score + reasons, has_more)."""
    stmt = apply_filters(select(SearchListing), f, tolerant_price=True)
    semantic = None
    if query_vector is not None:
        semantic = (1 - SearchListing.embedding.cosine_distance(query_vector)).label("semantic")
        stmt = stmt.add_columns(semantic).where(SearchListing.embedding.is_not(None))
        stmt = stmt.order_by(SearchListing.embedding.cosine_distance(query_vector))
    elif fts_query:
        ts_query = func.websearch_to_tsquery("english", fts_query)
        semantic = func.ts_rank(SearchListing.search_text, ts_query).label("semantic")
        stmt = stmt.add_columns(semantic).where(SearchListing.search_text.op("@@")(ts_query)).order_by(semantic.desc())
    else:
        stmt = stmt.add_columns(literal(0.0).label("semantic")).order_by(SearchListing.published_at.desc())
    rows = (await session.execute(stmt.limit(settings.rank_candidates))).all()

    scored = []
    for row, sem in rows:
        fit, reasons = _filter_fit(row, f)
        score = (
            settings.rank_w_semantic * float(sem or 0)
            + settings.rank_w_filter * fit
            + settings.rank_w_freshness * _freshness(row.published_at)
        )
        scored.append((row, round(score, 4), reasons))
    scored.sort(key=lambda item: (-item[1], str(item[0].id)))
    page = scored[offset : offset + limit]
    return page, offset + limit < len(scored)
