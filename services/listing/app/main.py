import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

import redis.asyncio as redis
import structlog
from fastapi import Depends, File, Form, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blob import BlobStore
from app.config import settings
from app.images import process_image
from app.mapping import to_documents, to_facts, to_out, to_snapshot, to_summary
from app.models import Listing, ListingDocument, ListingImage, ModerationAction
from app.money import money_out, rupees_to_minor
from app.rules import AGENT_STATUSES, duplicate_title, publish_problems
from app.schemas import (
    AdminListingOut,
    DocumentOut,
    ImageOrder,
    ListingCreate,
    ListingFields,
    ListingOut,
    ListingSummary,
    ListingUpdate,
    ModerationActionOut,
    ModerationRequest,
)
from estate_common import events
from estate_common.app import create_app, postgres_check, redis_check
from estate_common.auth import Admin, Agent, CurrentUser, OptionalUser
from estate_common.cache import TwoLevelCache
from estate_common.db import Database
from estate_common.errors import Conflict, Forbidden, NotFound, ValidationFailed
from estate_common.events import Event
from estate_common.http import ResilientClient
from estate_common.idempotency import IdempotencyMiddleware
from estate_common.messaging import consume_forever
from estate_common.outbox import OutboxRelay, add_event

log = structlog.get_logger(__name__)
db = Database(settings.database_url)
ai_http = ResilientClient("ai", settings.ai_url, settings=settings)
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


async def on_identity_event(event: Event) -> None:
    """Agent suspended → hide their live listings; reinstated → show them again; deleted → archive all.
    Idempotent: each transition only touches listings in the state it moves them from."""
    agent_id = uuid.UUID(event.data["user_id"])
    moves = {
        events.USER_SUSPENDED: ({"published"}, "suspended", events.LISTING_UNPUBLISHED),
        events.USER_REINSTATED: ({"suspended"}, "published", events.LISTING_PUBLISHED),
        events.USER_DELETED: ({"draft", "published", "unpublished", "suspended", "removed"}, "archived", events.LISTING_UNPUBLISHED),
    }
    from_states, to_state, event_type = moves[event.type]
    async with db.sessionmaker() as session:
        listings = list(await session.scalars(
            select(Listing).where(Listing.agent_id == agent_id, Listing.status.in_(from_states))
        ))
        for listing in listings:
            was_live = listing.status == "published"
            listing.status = to_state
            if was_live or to_state == "published":
                _stage_state(session, listing, event_type)
        await session.commit()
    for listing in listings:
        await listing_cache.invalidate(str(listing.id))
    log.info("agent_listings_moved", count=len(listings), to_state=to_state)


@asynccontextmanager
async def lifespan(_app):
    # Schema is managed by Alembic (`alembic upgrade head` runs before the server starts).
    await blobs.ensure_container()
    tasks = [
        asyncio.create_task(consume_forever(
            settings.servicebus_connection, events.AI_EVENTS, "listing", on_document_processed,
            handled_types={events.DOCUMENT_PROCESSED},
        )),
        asyncio.create_task(consume_forever(
            settings.servicebus_connection, events.IDENTITY_EVENTS, "listing", on_identity_event,
            handled_types={events.USER_SUSPENDED, events.USER_REINSTATED, events.USER_DELETED},
        )),
        asyncio.create_task(relay.run_forever()),
        asyncio.create_task(listing_cache.listen_for_invalidations()),
    ]
    yield
    for task in tasks:
        task.cancel()
    await blobs.close()
    await ai_http.aclose()


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


def _ensure_editable(listing: Listing, user: CurrentUser) -> None:
    """Owner check, plus: listings taken down by a moderator or hidden by a suspension are read-only."""
    _ensure_owner(listing, user)
    if listing.status not in AGENT_STATUSES and not user.is_admin:
        raise Forbidden("This listing was taken down by a moderator. Contact support to have it reviewed.")


async def _fair_housing_problems(listing: Listing) -> list[dict[str, str]]:
    """Requirements §7: no listing text may express preference or exclusion based on religion, caste,
    community, gender, marital status or diet. The deterministic check lives in the ai service's guardrails;
    if that service is down, publishing is not blocked (logged) — the AI dashboard re-checks later."""
    try:
        response = await ai_http.post("/internal/guardrails/listing-text", idempotent=True, json={
            "fields": {"title": listing.title, "description": listing.description or ""},
        })
        response.raise_for_status()
    except Exception:
        log.warning("fair_housing_check_unavailable", listing_id=str(listing.id))
        return []
    return [{"field": v["field"], "issue": f"discriminatory_wording: {v['phrase']}"} for v in response.json()["violations"]]


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
    _ensure_editable(listing, user)
    merged = {**_as_fields(listing), **body.model_dump(exclude_unset=True)}
    try:
        validated = ListingFields.model_validate(merged)
    except PydanticValidationError as exc:
        details = [{"field": ".".join(str(p) for p in e["loc"]) or "carpet_area_sqft", "issue": e["msg"]} for e in exc.errors()]
        raise ValidationFailed("Some details need fixing.", details) from exc
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
    _ensure_editable(listing, user)
    problems = publish_problems(listing) + await _fair_housing_problems(listing)
    if problems:
        raise ValidationFailed("Fill in the highlighted details before publishing.", problems)
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
    _ensure_editable(listing, user)
    was_live = listing.status == "published"
    listing.status = "unpublished"
    if was_live:
        _stage_state(session, listing, events.LISTING_UNPUBLISHED)
    await session.commit()
    await session.refresh(listing)
    await listing_cache.invalidate(str(listing.id))
    return to_out(listing)


@app.post("/api/v1/listings/{listing_id}/archive")
async def archive_listing(listing_id: uuid.UUID, user: Agent, session: Session) -> dict:
    """FR-1.1: archived listings leave search and the agent's list; they are kept for records only."""
    listing = await _get(session, listing_id)
    _ensure_owner(listing, user)
    was_live = listing.status == "published"
    listing.status = "archived"
    if was_live:
        _stage_state(session, listing, events.LISTING_UNPUBLISHED)
    await session.commit()
    await listing_cache.invalidate(str(listing.id))
    return {"id": str(listing.id), "status": "archived"}


@app.post("/api/v1/listings/{listing_id}/duplicate", status_code=201)
async def duplicate_listing(listing_id: uuid.UUID, user: Agent, session: Session) -> ListingOut:
    """FR-1.5: a new draft with the same details. Photos and documents are not copied."""
    source = await _get(session, listing_id)
    _ensure_owner(source, user)
    copy = Listing(agent_id=uuid.UUID(user.id) if not user.is_admin else source.agent_id)
    _apply(copy, {**_as_fields(source), "title": duplicate_title(source.title), "description_ai": False})
    copy.images, copy.documents = [], []
    session.add(copy)
    await session.commit()
    await session.refresh(copy)
    return to_out(copy)


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
    _ensure_editable(listing, user)
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
    # Images are public. Documents are served only to the owner (download_document below).
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
    _ensure_editable(listing, user)
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


async def _restage_if_live(session: AsyncSession, listing: Listing) -> None:
    await session.flush()
    await session.refresh(listing)
    if listing.status == "published":
        _stage_state(session, listing, events.LISTING_UPDATED)  # thumbnail may have changed


@app.put("/api/v1/listings/{listing_id}/images/order")
async def reorder_images(listing_id: uuid.UUID, body: ImageOrder, user: Agent, session: Session) -> ListingOut:
    """FR-1.2: the first image is the cover photo and the search thumbnail."""
    listing = await _get(session, listing_id)
    _ensure_editable(listing, user)
    by_id = {image.id: image for image in listing.images}
    if set(body.image_ids) != set(by_id) or len(body.image_ids) != len(by_id):
        raise ValidationFailed("Send every photo of this listing exactly once.", [{"field": "image_ids", "issue": "mismatch"}])
    for position, image_id in enumerate(body.image_ids):
        by_id[image_id].position = position
    await _restage_if_live(session, listing)
    await session.commit()
    await listing_cache.invalidate(str(listing.id))
    return to_out(listing)


@app.delete("/api/v1/listings/{listing_id}/images/{image_id}")
async def delete_image(listing_id: uuid.UUID, image_id: uuid.UUID, user: Agent, session: Session) -> ListingOut:
    listing = await _get(session, listing_id)
    _ensure_editable(listing, user)
    image = next((i for i in listing.images if i.id == image_id), None)
    if image is None:
        raise NotFound("Photo not found.")
    keys = [image.storage_key, image.thumb_key]
    listing.images.remove(image)
    for position, remaining in enumerate(listing.images):
        remaining.position = position
    await _restage_if_live(session, listing)
    await session.commit()
    await listing_cache.invalidate(str(listing.id))
    for key in keys:
        await blobs.delete(key)  # after commit: a leftover blob is harmless, a missing one is not
    return to_out(listing)


async def _owned_document(session: AsyncSession, listing_id: uuid.UUID, document_id: uuid.UUID,
                          user: CurrentUser) -> ListingDocument:
    listing = await _get(session, listing_id)
    _ensure_owner(listing, user)
    document = next((d for d in listing.documents if d.id == document_id), None)
    if document is None:
        raise NotFound("Document not found.")
    return document


@app.get("/api/v1/listings/{listing_id}/documents/{document_id}/file")
async def download_document(listing_id: uuid.UUID, document_id: uuid.UUID, user: Agent, session: Session) -> Response:
    """Owner-only PDF download (T3c.8). Buyers never get the file, only cited answers from it."""
    document = await _owned_document(session, listing_id, document_id, user)
    data, _content_type = await blobs.download(document.storage_key)
    safe_name = "".join(c for c in document.filename if c.isalnum() or c in "._- ")[:100] or "document.pdf"
    return Response(content=data, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename=\"{safe_name}\"", "Cache-Control": "private, no-store",
    })


@app.delete("/api/v1/listings/{listing_id}/documents/{document_id}", status_code=204)
async def delete_document(listing_id: uuid.UUID, document_id: uuid.UUID, user: Agent, session: Session) -> None:
    """Removes the PDF; the ai service drops its chunks on listing.document_deleted, so Q&A stops citing it."""
    document = await _owned_document(session, listing_id, document_id, user)
    key = document.storage_key
    await session.delete(document)
    add_event(session, topic=events.LISTING_EVENTS, event_type=events.LISTING_DOCUMENT_DELETED, subject=str(listing_id),
              source="listing", data={"document_id": str(document_id), "listing_id": str(listing_id)})
    await session.commit()
    await blobs.delete(key)


# ─────────────────────────────── admin moderation (FR-7.1) ───────────────────────────────
def _action_out(action: ModerationAction) -> ModerationActionOut:
    return ModerationActionOut(id=action.id, action=action.action, reason=action.reason,
                               admin_id=action.admin_id, created_at=action.created_at)


def _admin_out(listing: Listing, last: ModerationAction | None) -> AdminListingOut:
    return AdminListingOut(
        id=listing.id, agent_id=listing.agent_id, status=listing.status, title=listing.title,
        locality=listing.locality, city=listing.city, price=money_out(listing.price_minor, listing.currency),
        updated_at=listing.updated_at, last_action=_action_out(last) if last else None,
    )


@app.get("/api/v1/admin/listings")
async def admin_listings(
    _admin: Admin, session: Session,
    q: str | None = Query(None, max_length=100, description="Title, locality or listing id"),
    status: str | None = Query(None, pattern=r"^(draft|published|unpublished|removed|suspended|archived)$"),
    limit: int = Query(50, ge=1, le=200),
) -> list[AdminListingOut]:
    stmt = select(Listing).order_by(Listing.updated_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Listing.status == status)
    if q:
        term = q.strip()
        conditions: list[ColumnElement[bool]] = [Listing.title.ilike(f"%{term}%"), Listing.locality.ilike(f"%{term}%")]
        try:
            conditions.append(Listing.id == uuid.UUID(term))
        except ValueError:
            pass
        stmt = stmt.where(or_(*conditions))
    listings = list(await session.scalars(stmt))
    last: dict[uuid.UUID, ModerationAction] = {}
    if listings:
        actions = await session.scalars(
            select(ModerationAction).where(ModerationAction.listing_id.in_([x.id for x in listings]))
            .order_by(ModerationAction.created_at)
        )
        last = {a.listing_id: a for a in actions}
    return [_admin_out(x, last.get(x.id)) for x in listings]


@app.get("/api/v1/admin/listings/{listing_id}/moderation")
async def moderation_history(listing_id: uuid.UUID, _admin: Admin, session: Session) -> list[ModerationActionOut]:
    actions = await session.scalars(
        select(ModerationAction).where(ModerationAction.listing_id == listing_id).order_by(ModerationAction.created_at.desc())
    )
    return [_action_out(a) for a in actions]


async def _moderate(session: AsyncSession, listing_id: uuid.UUID, admin: CurrentUser, action: str,
                    reason: str) -> AdminListingOut:
    listing = await session.get(Listing, listing_id)
    if listing is None:
        raise NotFound("Listing not found.")
    if action == "takedown":
        if listing.status != "published":
            raise Conflict("Only live listings can be taken down.")
        listing.status = "removed"
        _stage_state(session, listing, events.LISTING_UNPUBLISHED)
    else:
        if listing.status != "removed":
            raise Conflict("Only taken-down listings can be restored.")
        listing.status = "published"
        _stage_state(session, listing, events.LISTING_PUBLISHED)
    entry = ModerationAction(listing_id=listing.id, admin_id=uuid.UUID(admin.id), action=action, reason=reason.strip())
    session.add(entry)
    await session.commit()
    await session.refresh(listing)
    await session.refresh(entry)
    await listing_cache.invalidate(str(listing.id))
    log.info("listing_moderated", listing_id=str(listing.id), action=action)  # the reason stays in the audit table
    return _admin_out(listing, entry)


@app.post("/api/v1/admin/listings/{listing_id}/takedown")
async def takedown_listing(listing_id: uuid.UUID, body: ModerationRequest, admin: Admin, session: Session) -> AdminListingOut:
    return await _moderate(session, listing_id, admin, "takedown", body.reason)


@app.post("/api/v1/admin/listings/{listing_id}/restore")
async def restore_listing(listing_id: uuid.UUID, body: ModerationRequest, admin: Admin, session: Session) -> AdminListingOut:
    return await _moderate(session, listing_id, admin, "restore", body.reason)


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
