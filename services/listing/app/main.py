import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

import redis.asyncio as redis
from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blob import BlobStore
from app.config import settings
from app.images import process_image
from app.mapping import to_documents, to_facts, to_out, to_snapshot, to_summary
from app.models import Listing, ListingDocument, ListingImage
from app.money import rupees_to_minor
from app.schemas import DocumentOut, ListingCreate, ListingFields, ListingOut, ListingSummary, ListingUpdate
from estate_common import events
from estate_common.app import create_app, postgres_check, redis_check
from estate_common.auth import Agent, CurrentUser, OptionalUser
from estate_common.cache import TwoLevelCache
from estate_common.db import Database
from estate_common.errors import Conflict, Forbidden, NotFound, ValidationFailed
from estate_common.events import Event
from estate_common.idempotency import IdempotencyMiddleware
from estate_common.messaging import consume_forever
from estate_common.outbox import OutboxRelay, add_event

db = Database(settings.database_url)
blobs = BlobStore(settings.storage_connection, settings.media_container)
cache_redis = redis.from_url(settings.redis_url)
# Public listing pages: L1 10 s per replica, L2 5 min in Redis; invalidated on every write below.
listing_cache = TwoLevelCache(cache_redis, "listing", l1_ttl_s=10, l2_ttl_s=300)
relay = OutboxRelay(db, settings.servicebus_connection)
Session = Annotated[AsyncSession, Depends(db.session)]

MONEY_FIELDS = {"price_inr": "price_minor", "deposit_inr": "deposit_minor", "maintenance_inr": "maintenance_minor"}


async def on_document_processed(event: Event) -> None:
    async with db.sessionmaker() as session:
        document = await session.get(ListingDocument, uuid.UUID(event.data["document_id"]))
        if document is None:
            return
        document.status = event.data["status"]
        document.error = event.data.get("error")
        await session.commit()


@asynccontextmanager
async def lifespan(_app):
    # Schema is managed by Alembic (`alembic upgrade head` runs before the server starts).
    await blobs.ensure_container()
    tasks = [
        asyncio.create_task(consume_forever(
            settings.servicebus_connection, events.AI_EVENTS, "listing", on_document_processed,
            handled_types={events.DOCUMENT_PROCESSED},
        )),
        asyncio.create_task(relay.run_forever()),
        asyncio.create_task(listing_cache.listen_for_invalidations()),
    ]
    yield
    for task in tasks:
        task.cancel()
    await blobs.close()


app = create_app(settings, title="Listing Service", lifespan=lifespan,
                 readiness={"postgres": postgres_check(db), "redis": redis_check(cache_redis)})
app.add_middleware(IdempotencyMiddleware, client=cache_redis, service="listing", paths=[r"/api/v1/listings"])


# ─────────────────────────────── helpers ───────────────────────────────
async def _get(session: AsyncSession, listing_id: uuid.UUID) -> Listing:
    listing = await session.get(Listing, listing_id)
    if listing is None or listing.status == "archived":
        raise NotFound("Listing not found.")
    return listing


def _ensure_owner(listing: Listing, user: CurrentUser) -> None:
    if not (user.is_admin or str(listing.agent_id) == user.id):
        raise Forbidden("You can only manage your own listings.")


def _apply(listing: Listing, fields: dict) -> None:
    for key, value in fields.items():
        if key in MONEY_FIELDS:
            setattr(listing, MONEY_FIELDS[key], rupees_to_minor(value) if value is not None else None)
        else:
            setattr(listing, key, value)


def _as_fields(listing: Listing) -> dict:
    data = {k: getattr(listing, k) for k in ListingFields.model_fields if k not in MONEY_FIELDS}
    for api_field, column in MONEY_FIELDS.items():
        minor = getattr(listing, column)
        data[api_field] = minor // 100 if minor is not None else None
    return data


def _stage_state(session: AsyncSession, listing: Listing, event_type: str) -> None:
    """Stage a listing event in the same transaction as the change (transactional outbox, ADR-0016)."""
    add_event(session, topic=events.LISTING_EVENTS, event_type=event_type, subject=str(listing.id),
              data=to_snapshot(listing), source="listing")


# ─────────────────────────────── public / agent API ───────────────────────────────
@app.get("/api/v1/listings/{listing_id}")
async def get_listing(listing_id: uuid.UUID, user: OptionalUser, session: Session) -> ListingOut:
    if user is not None:
        listing = await _get(session, listing_id)
        if user.is_admin or user.id == str(listing.agent_id):
            return to_out(listing)  # owners see drafts and fresh data; never cached

    async def load_published() -> dict | None:
        row = await session.get(Listing, listing_id)
        return to_out(row).model_dump(mode="json") if row is not None and row.status == "published" else None

    data = await listing_cache.get_or_load(str(listing_id), load_published)
    if data is None:
        raise NotFound("Listing not found.")
    return ListingOut.model_validate(data)


@app.post("/api/v1/listings", status_code=201)
async def create_listing(body: ListingCreate, user: Agent, session: Session) -> ListingOut:
    if not user.agent_verified and not user.is_admin:
        raise Forbidden("Your agent account is not verified yet.")
    listing = Listing(agent_id=uuid.UUID(user.id))
    _apply(listing, body.model_dump())
    session.add(listing)
    await session.commit()
    await session.refresh(listing)
    return to_out(listing)


@app.patch("/api/v1/listings/{listing_id}")
async def update_listing(listing_id: uuid.UUID, body: ListingUpdate, user: Agent, session: Session) -> ListingOut:
    listing = await _get(session, listing_id)
    _ensure_owner(listing, user)
    merged = {**_as_fields(listing), **body.model_dump(exclude_unset=True)}
    try:
        validated = ListingFields.model_validate(merged)
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    _apply(listing, validated.model_dump())
    if listing.status == "published":
        _stage_state(session, listing, events.LISTING_UPDATED)
    await session.commit()
    await session.refresh(listing)
    await listing_cache.invalidate(str(listing.id))
    return to_out(listing)


@app.post("/api/v1/listings/{listing_id}/publish")
async def publish_listing(listing_id: uuid.UUID, user: Agent, session: Session) -> ListingOut:
    listing = await _get(session, listing_id)
    _ensure_owner(listing, user)
    if not listing.description:
        raise ValidationFailed("Add a description before publishing.", [{"field": "description", "issue": "required"}])
    listing.status = "published"
    listing.published_at = listing.published_at or datetime.now(UTC)
    _stage_state(session, listing, events.LISTING_PUBLISHED)
    await session.commit()
    await session.refresh(listing)
    await listing_cache.invalidate(str(listing.id))
    return to_out(listing)


@app.post("/api/v1/listings/{listing_id}/unpublish")
async def unpublish_listing(listing_id: uuid.UUID, user: Agent, session: Session) -> ListingOut:
    listing = await _get(session, listing_id)
    _ensure_owner(listing, user)
    listing.status = "unpublished"
    _stage_state(session, listing, events.LISTING_UNPUBLISHED)
    await session.commit()
    await session.refresh(listing)
    await listing_cache.invalidate(str(listing.id))
    return to_out(listing)


@app.get("/api/v1/agent/listings")
async def my_listings(user: Agent, session: Session) -> list[ListingSummary]:
    rows = await session.scalars(
        select(Listing).where(Listing.agent_id == uuid.UUID(user.id), Listing.status != "archived").order_by(Listing.updated_at.desc())
    )
    return [to_summary(r) for r in rows]


@app.post("/api/v1/listings/{listing_id}/images", status_code=201)
async def upload_image(
    listing_id: uuid.UUID, user: Agent, session: Session,
    file: Annotated[UploadFile, File()], caption: Annotated[str | None, Form()] = None,
) -> ListingOut:
    listing = await _get(session, listing_id)
    _ensure_owner(listing, user)
    if len(listing.images) >= settings.max_images_per_listing:
        raise Conflict("Image limit reached for this listing.")
    raw = await file.read(settings.max_image_mb * 1024 * 1024 + 1)
    if len(raw) > settings.max_image_mb * 1024 * 1024:
        raise ValidationFailed(f"Images must be at most {settings.max_image_mb} MB.")
    display, thumb = await run_in_threadpool(process_image, raw)
    image_id = uuid.uuid4()
    key, thumb_key = f"listings/{listing.id}/images/{image_id}.webp", f"listings/{listing.id}/images/{image_id}_thumb.webp"
    await blobs.upload(key, display, "image/webp")
    await blobs.upload(thumb_key, thumb, "image/webp")
    session.add(ListingImage(id=image_id, listing_id=listing.id, storage_key=key, thumb_key=thumb_key,
                             caption=caption, position=len(listing.images)))
    await session.flush()
    await session.refresh(listing)
    if listing.status == "published":
        _stage_state(session, listing, events.LISTING_UPDATED)
    await session.commit()
    await listing_cache.invalidate(str(listing.id))
    return to_out(listing)


@app.get("/api/v1/media/{key:path}")
async def get_media(key: str) -> Response:
    # Images are public. Documents are served only via the owner endpoints (not implemented yet — T3c.8).
    if "/images/" not in key:
        raise NotFound("File not found.")
    data, content_type = await blobs.download(key)
    return Response(content=data, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/v1/listings/{listing_id}/documents", status_code=201)
async def upload_document(
    listing_id: uuid.UUID, user: Agent, session: Session,
    file: Annotated[UploadFile, File()], kind: Annotated[str, Form()] = "other",
) -> DocumentOut:
    listing = await _get(session, listing_id)
    _ensure_owner(listing, user)
    if len(listing.documents) >= settings.max_documents_per_listing:
        raise Conflict("Document limit reached for this listing.")
    raw = await file.read(settings.max_document_mb * 1024 * 1024 + 1)
    if len(raw) > settings.max_document_mb * 1024 * 1024:
        raise ValidationFailed(f"Documents must be at most {settings.max_document_mb} MB.")
    if not raw.startswith(b"%PDF-"):
        raise ValidationFailed("Only PDF documents are supported.")
    document = ListingDocument(listing_id=listing.id, filename=(file.filename or "document.pdf")[:200],
                               kind=kind if kind in {"floor_plan", "society_rules", "brochure"} else "other",
                               storage_key="", status="processing")
    session.add(document)
    await session.flush()
    document.storage_key = f"listings/{listing.id}/documents/{document.id}.pdf"
    await blobs.upload(document.storage_key, raw, "application/pdf")
    add_event(session, topic=events.LISTING_EVENTS, event_type=events.LISTING_DOCUMENT_UPLOADED, subject=str(listing.id),
              source="listing", data={
                  "document_id": str(document.id), "listing_id": str(listing.id),
                  "storage_key": document.storage_key, "filename": document.filename, "kind": document.kind,
              })
    await session.commit()
    return DocumentOut(id=document.id, filename=document.filename, kind=document.kind,
                       status=document.status, error=None, created_at=document.created_at or datetime.now(UTC))


@app.get("/api/v1/listings/{listing_id}/documents")
async def list_documents(listing_id: uuid.UUID, user: Agent, session: Session) -> list[DocumentOut]:
    listing = await _get(session, listing_id)
    _ensure_owner(listing, user)
    return to_documents(listing)


# ─────────────────────────────── internal (service-to-service) ───────────────────────────────
@app.get("/internal/listings/{listing_id}/facts")
async def internal_facts(listing_id: uuid.UUID, session: Session) -> dict:
    listing = await _get(session, listing_id)
    return {
        "listing_id": str(listing.id),
        "agent_id": str(listing.agent_id),
        "status": listing.status,
        "title": listing.title,
        "description": listing.description,
        "image_captions": [i.caption for i in listing.images if i.caption],
        "facts": to_facts(listing),
    }


@app.get("/internal/listings/{listing_id}/summary")
async def internal_summary(listing_id: uuid.UUID, session: Session) -> dict:
    listing = await _get(session, listing_id)
    return {"id": str(listing.id), "agent_id": str(listing.agent_id), "title": listing.title, "status": listing.status}


@app.post("/internal/dev/seed")
async def internal_seed(request: Request) -> dict:
    """Local-only: create sample listings for the dev agent. See app/seed.py."""
    if not settings.is_local:
        raise NotFound("Not available.")
    from app.seed import seed

    count = int(request.query_params.get("count", "60"))
    return {"created": await seed(db, count)}


@app.post("/internal/dev/republish")
async def internal_republish() -> dict:
    """Re-emit listing.updated for every published listing so read models (search) can rebuild (T2.10)."""
    if not settings.is_local:
        raise NotFound("Not available.")
    async with db.sessionmaker() as session:
        listings = list(await session.scalars(select(Listing).where(Listing.status == "published")))
        for listing in listings:
            _stage_state(session, listing, events.LISTING_UPDATED)
        await session.commit()
    return {"republished": len(listings)}
