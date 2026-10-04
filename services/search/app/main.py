import asyncio
import base64
import hashlib
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal

import redis.asyncio as redis
import structlog
from fastapi import Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_client import AIClient
from app.config import settings
from app.models import SearchListing, embedding_text
from app.ranking import Filters, apply_filters, hybrid_search, parse_bbox
from estate_common import events
from estate_common.app import create_app, postgres_check, redis_check
from estate_common.cache import TwoLevelCache
from estate_common.db import Database
from estate_common.events import Event
from estate_common.flags import FeatureFlags
from estate_common.messaging import consume_forever

log = structlog.get_logger(__name__)
db = Database(settings.database_url)
ai = AIClient()
cache = redis.from_url(settings.redis_url)
# Classic filter search: L1 10 s, L2 60 s, versioned — any listing event bumps the version (clears it all).
search_cache = TwoLevelCache(cache, "search", l1_ttl_s=10, l2_ttl_s=60)
flags = FeatureFlags(cache, {"nl_search": settings.feature_nl_search})  # admins toggle it at runtime (FR-7.4)
Session = Annotated[AsyncSession, Depends(db.session)]


# ─────────────────────────────── projection (event consumer) ───────────────────────────────
async def on_listing_event(event: Event) -> None:
    data = event.data
    async with db.sessionmaker() as session:
        if event.type == events.LISTING_UNPUBLISHED or data.get("status") != "published":
            await session.execute(delete(SearchListing).where(SearchListing.id == uuid.UUID(data["id"])))
            await session.commit()
            await search_cache.bump_version()
            return
        try:
            [vector] = await ai.embed([embedding_text(data)], input_type="document")
        except Exception:
            log.warning("embedding_failed_indexing_without_vector", listing_id=data["id"])
            vector = None
        row = {
            "id": uuid.UUID(data["id"]),
            **{k: data.get(k) for k in (
                "listing_type", "property_type", "title", "description", "price_minor", "currency", "bedrooms",
                "bathrooms", "carpet_area_sqft", "furnishing", "pet_policy", "amenities", "locality", "city",
                "lat", "lng", "thumbnail_key",
            )},
            "published_at": datetime.fromisoformat(data["published_at"]) if data.get("published_at") else None,
            "embedding": vector,
        }
        stmt = insert(SearchListing).values(**row)
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_={k: stmt.excluded[k] for k in row if k != "id"})
        await session.execute(stmt)
        await session.commit()
    await search_cache.bump_version()


@asynccontextmanager
async def lifespan(_app):
    # Schema (incl. the pgvector extension) is managed by Alembic.
    tasks = [
        asyncio.create_task(consume_forever(
            settings.servicebus_connection, events.LISTING_EVENTS, "search", on_listing_event,
            handled_types={events.LISTING_PUBLISHED, events.LISTING_UPDATED, events.LISTING_UNPUBLISHED})),
        asyncio.create_task(search_cache.listen_for_invalidations()),
    ]
    yield
    for task in tasks:
        task.cancel()
    await ai.close()


app = create_app(settings, title="Search Service", lifespan=lifespan,
                 readiness={"postgres": postgres_check(db), "redis": redis_check(cache)})


# ─────────────────────────────── API models ───────────────────────────────
class Money(BaseModel):
    amount_minor: int
    currency: str
    display: str


Near = Literal["metro", "school", "hospital", "it_park", "mall", "railway_station", "airport"]


class ResultItem(BaseModel):
    id: uuid.UUID
    title: str
    listing_type: str
    property_type: str
    price: Money
    bedrooms: int
    bathrooms: int | None
    carpet_area_sqft: int | None
    locality: str
    city: str
    lat: float | None
    lng: float | None
    thumbnail_url: str | None
    match: dict


class SearchResponse(BaseModel):
    items: list[ResultItem]
    next_cursor: str | None
    interpreted_filters: dict | None = None
    assumptions: list[str] = []
    is_property_query: bool = True
    meta: dict = {}


def _display(minor: int) -> str:
    rupees = minor // 100
    if rupees >= 10_000_000:
        return f"₹{rupees / 10_000_000:.2f}".rstrip("0").rstrip(".") + " Cr"
    if rupees >= 100_000:
        return f"₹{rupees / 100_000:.2f}".rstrip("0").rstrip(".") + " L"
    return f"₹{rupees:,}"


def _item(row: SearchListing, score: float, reasons: list[str]) -> ResultItem:
    return ResultItem(
        id=row.id, title=row.title, listing_type=row.listing_type, property_type=row.property_type,
        price=Money(amount_minor=row.price_minor, currency=row.currency, display=_display(row.price_minor)),
        bedrooms=row.bedrooms, bathrooms=row.bathrooms, carpet_area_sqft=row.carpet_area_sqft,
        locality=row.locality, city=row.city, lat=row.lat, lng=row.lng,
        thumbnail_url=f"/api/v1/media/{row.thumbnail_key}" if row.thumbnail_key else None,
        match={"score": score, "reasons": reasons},
    )


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return max(0, int(base64.urlsafe_b64decode(cursor.encode()).decode()))
    except ValueError:
        return 0


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


# ─────────────────────────────── classic search (FR-2) ───────────────────────────────
@app.get("/api/v1/search")
async def classic_search(
    session: Session,
    city: str | None = None,
    locality: str | None = None,
    listing_type: Literal["sale", "rent"] | None = None,
    property_type: str | None = None,
    bedrooms_min: int | None = Query(None, ge=0),
    bedrooms_max: int | None = Query(None, ge=0),
    price_min: int | None = Query(None, ge=0, description="rupees"),
    price_max: int | None = Query(None, ge=0, description="rupees"),
    furnishing: str | None = None,
    pet_policy: str | None = None,
    amenities: Annotated[list[str] | None, Query()] = None,
    near: Annotated[list[Near] | None, Query(description="Ranks homes closer to these places first")] = None,
    bbox: str | None = Query(None, description="minLng,minLat,maxLng,maxLat — only homes on this part of the map"),
    sort: Literal["relevance", "price_asc", "price_desc", "newest"] = "newest",
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=50),
) -> SearchResponse:
    f = Filters(city=city, locality=locality, listing_type=listing_type, property_type=property_type,
                bedrooms_min=bedrooms_min, bedrooms_max=bedrooms_max,
                price_min_minor=price_min * 100 if price_min else None,
                price_max_minor=price_max * 100 if price_max else None,
                furnishing=furnishing, pet_policy=pet_policy, amenities=amenities or [], near=near or [],
                bbox=parse_bbox(bbox))
    offset = _decode_cursor(cursor)

    async def run_query() -> dict:
        if sort == "relevance" or f.near:
            # Relevance without a text query: filter fit (exact locality, within budget) + near + freshness.
            results, has_more = await hybrid_search(session, f, None, None, offset, limit, sort)
            return SearchResponse(
                items=[_item(row, score, reasons) for row, score, reasons in results],
                next_cursor=_encode_cursor(offset + limit) if has_more else None,
                meta={"mode": "classic", "sort": sort},
            ).model_dump(mode="json")
        order = {
            "price_asc": SearchListing.price_minor.asc(),
            "price_desc": SearchListing.price_minor.desc(),
        }.get(sort, SearchListing.published_at.desc())
        stmt = apply_filters(select(SearchListing), f).order_by(order, SearchListing.id).offset(offset).limit(limit + 1)
        rows = list(await session.scalars(stmt))
        return SearchResponse(
            items=[_item(r, 0.0, []) for r in rows[:limit]],
            next_cursor=_encode_cursor(offset + limit) if len(rows) > limit else None,
            meta={"mode": "classic", "sort": sort},
        ).model_dump(mode="json")

    key = json.dumps([f.__dict__, sort, offset, limit], sort_keys=True, default=str)
    return SearchResponse.model_validate(await search_cache.get_or_load(key, run_query, versioned=True))


# ─────────────────────────────── NL search (FR-3) ───────────────────────────────
class NLSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    cursor: str | None = None
    limit: int = Field(20, ge=1, le=50)
    sort: Literal["relevance", "price_asc", "price_desc", "newest"] = "relevance"
    bbox: str | None = Field(None, max_length=100, description="minLng,minLat,maxLng,maxLat")


async def _parse_with_cache(query: str) -> tuple[dict | None, bool]:
    key = "nl:" + hashlib.sha256(" ".join(query.lower().split()).encode()).hexdigest()
    try:
        cached = await cache.get(key)
        if cached:
            return json.loads(cached), True
    except redis.RedisError:
        pass
    try:
        parsed = await ai.parse_query(query, timeout=settings.nl_parse_timeout_s)
    except Exception:
        log.warning("nl_parse_failed_using_fallback")
        return None, False
    try:
        await cache.set(key, json.dumps(parsed), ex=settings.nl_search_cache_ttl_s)
    except redis.RedisError:
        pass
    return parsed, False


async def _embed_query(query: str) -> list[float] | None:
    try:
        [vector] = await ai.embed([query], input_type="query", timeout=settings.embed_timeout_s)
        return vector
    except Exception:
        log.warning("query_embedding_failed")
        return None


@app.post("/api/v1/search/nl")
async def nl_search(body: NLSearchRequest, session: Session) -> SearchResponse:
    parsed, cached = None, False
    if await flags.is_enabled("nl_search"):
        (parsed, cached), vector = await asyncio.gather(_parse_with_cache(body.query), _embed_query(body.query))
    else:
        vector = await _embed_query(body.query)

    if parsed and not parsed["filters"].get("is_property_query", True):
        return SearchResponse(items=[], next_cursor=None, is_property_query=False, interpreted_filters=parsed["filters"],
                              meta={"mode": "ai", "ai_request_id": parsed.get("ai_request_id")})

    f = Filters()
    if parsed:
        pf = parsed["filters"]
        f = Filters(
            city=pf.get("city"), locality=pf.get("locality"), listing_type=pf.get("listing_type"),
            property_type=pf.get("property_type"), bedrooms_min=pf.get("bedrooms_min"), bedrooms_max=pf.get("bedrooms_max"),
            price_min_minor=pf["price_min_inr"] * 100 if pf.get("price_min_inr") else None,
            price_max_minor=pf["price_max_inr"] * 100 if pf.get("price_max_inr") else None,
            furnishing=pf.get("furnishing"), pet_policy=pf.get("pet_policy"), amenities=pf.get("amenities") or [],
            near=pf.get("near") or [],
        )
    f.bbox = parse_bbox(body.bbox)
    offset = _decode_cursor(body.cursor)
    results, has_more = await hybrid_search(session, f, vector, None if vector else body.query, offset, body.limit, body.sort)
    return SearchResponse(
        items=[_item(row, score, reasons) for row, score, reasons in results],
        next_cursor=_encode_cursor(offset + body.limit) if has_more else None,
        interpreted_filters=parsed["filters"] if parsed else None,
        assumptions=parsed["filters"].get("assumptions", []) if parsed else ["Showing broad matches for your search."],
        meta={"mode": "ai" if parsed else "fallback", "cached": cached,
              "ai_request_id": parsed.get("ai_request_id") if parsed else None},
    )
