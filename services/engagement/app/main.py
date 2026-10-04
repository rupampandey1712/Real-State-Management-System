"""Engagement service: enquiries, favourites, saved searches (Cosmos DB).

Events: Cosmos has no cross-container transactions, so each enquiry document carries its own outbox
flag (`eventPublished`). The request publishes right away; a relay re-publishes anything still unsent.
The event id is derived from the enquiry id, so Service Bus duplicate detection drops repeats (ADR-0016).
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis
import structlog
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.config import settings
from app.privacy import erase_user, purge_old_enquiries
from app.store import store
from estate_common import events
from estate_common.app import create_app, redis_check
from estate_common.auth import Agent, OptionalUser, User
from estate_common.errors import DependencyUnavailable, NotFound, ValidationFailed
from estate_common.http import ResilientClient
from estate_common.idempotency import IdempotencyMiddleware
from estate_common.events import Event
from estate_common.messaging import EventPublisher, consume_forever

log = structlog.get_logger(__name__)
publisher = EventPublisher(settings.servicebus_connection, source="engagement")
listing_http = ResilientClient("listing", settings.listing_url, settings=settings)
idempotency_redis = redis.from_url(settings.redis_url)
RELAY_INTERVAL_S = 30


@asynccontextmanager
async def lifespan(_app):
    for attempt in range(30):  # the Cosmos emulator can take a while to start
        try:
            await store.init()
            break
        except Exception:
            log.warning("cosmos_not_ready_retrying", attempt=attempt)
            await asyncio.sleep(5)
    tasks = [
        asyncio.create_task(relay_unpublished_enquiries()),
        asyncio.create_task(retention_forever()),
        asyncio.create_task(consume_forever(settings.servicebus_connection, events.IDENTITY_EVENTS, "engagement",
                                            on_identity_event, handled_types={events.USER_DELETED})),
    ]
    yield
    for task in tasks:
        task.cancel()
    await store.close()
    await listing_http.aclose()


async def cosmos_check() -> None:
    await store.client.get_database_client(settings.cosmos_database).read()


app = create_app(settings, title="Engagement Service", lifespan=lifespan,
                 readiness={"cosmos": cosmos_check, "redis": redis_check(idempotency_redis)})
app.add_middleware(IdempotencyMiddleware, client=idempotency_redis, service="engagement",
                   paths=[r"/api/v1/listings/[^/]+/enquiries", r"/api/v1/me/saved-searches"])


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def _listing_summary(listing_id: str) -> dict:
    response = await listing_http.get(f"/internal/listings/{listing_id}/summary")
    if response.status_code == 404:
        raise NotFound("Listing not found.")
    if response.status_code >= 400:
        raise DependencyUnavailable("Listing details are temporarily unavailable.")
    return response.json()


async def publish_enquiry_event(enquiry: dict) -> bool:
    """Publish engagement.enquiry_created (ids only, no PII) and mark the document. Safe to repeat."""
    try:
        await publisher.publish(
            events.ENGAGEMENT_EVENTS, events.ENQUIRY_CREATED, enquiry["listingId"],
            {"enquiry_id": enquiry["id"], "agent_id": enquiry["agentId"], "listing_id": enquiry["listingId"]},
            event_id="enquiry-" + enquiry["id"],
        )
    except Exception:
        log.warning("enquiry_event_publish_failed_will_retry", enquiry_id=enquiry["id"])
        return False
    enquiry["eventPublished"] = True
    await store["enquiries"].replace_item(item=enquiry["id"], body=enquiry)
    return True


async def relay_unpublished_enquiries() -> None:
    while True:
        await asyncio.sleep(RELAY_INTERVAL_S)
        try:
            cutoff = (datetime.now(UTC) - timedelta(seconds=RELAY_INTERVAL_S)).isoformat()
            pending = store["enquiries"].query_items(
                query="SELECT * FROM c WHERE c.eventPublished = false AND c.createdAt < @cutoff",
                parameters=[{"name": "@cutoff", "value": cutoff}],
            )
            async for enquiry in pending:
                await publish_enquiry_event(enquiry)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("enquiry_relay_error")


async def on_identity_event(event: Event) -> None:
    counts = await erase_user(store, event.data["user_id"])
    log.info("user_data_erased", **counts)


async def retention_forever() -> None:
    while True:
        try:
            if purged := await purge_old_enquiries(store):
                log.info("old_enquiries_purged", count=purged)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("enquiry_retention_failed")
        await asyncio.sleep(settings.retention_interval_s)


# ─────────────────────────────── enquiries (FR-6.3) ───────────────────────────────
class EnquiryIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(None, pattern=r"^\+?[0-9 \-]{8,16}$")
    message: str = Field(min_length=1, max_length=2000)
    source: str = Field("listing_page", pattern=r"^(listing_page|qa_unknown)$")
    # DPDP Act 2023: explicit consent to share these details with this listing's agent, for this enquiry only.
    consent: Literal[True]


@app.post("/api/v1/listings/{listing_id}/enquiries", status_code=201)
async def create_enquiry(listing_id: str, body: EnquiryIn, user: OptionalUser) -> dict:
    summary = await _listing_summary(listing_id)
    if summary["status"] != "published":
        raise ValidationFailed("This listing is not accepting enquiries.")
    enquiry = {
        "id": uuid.uuid4().hex,
        "agentId": summary["agent_id"],
        "listingId": listing_id,
        "listingTitle": summary["title"],
        "buyerId": user.id if user else None,
        **body.model_dump(exclude={"consent"}),
        "consentAt": _now(),
        "createdAt": _now(),
        "eventPublished": False,
    }
    await store["enquiries"].create_item(enquiry)
    await publish_enquiry_event(enquiry)  # on failure the relay retries; the enquiry itself is saved
    return {"id": enquiry["id"], "created_at": enquiry["createdAt"]}


@app.get("/api/v1/agent/enquiries")
async def agent_enquiries(user: Agent) -> list[dict]:
    return await store.query(
        "enquiries", "SELECT * FROM c WHERE c.agentId = @agent ORDER BY c.createdAt DESC",
        [{"name": "@agent", "value": user.id}], partition_key=user.id,
    )


@app.get("/internal/enquiries/{agent_id}/{enquiry_id}")
async def internal_get_enquiry(agent_id: str, enquiry_id: str) -> dict:
    try:
        return await store["enquiries"].read_item(item=enquiry_id, partition_key=agent_id)
    except CosmosResourceNotFoundError as exc:
        raise NotFound("Enquiry not found.") from exc


# ─────────────────────────────── favourites (FR-6.2) ───────────────────────────────
@app.get("/api/v1/me/favourites")
async def list_favourites(user: User) -> list[dict]:
    return await store.query(
        "favourites", "SELECT c.listingId, c.createdAt FROM c WHERE c.userId = @u ORDER BY c.createdAt DESC",
        [{"name": "@u", "value": user.id}], partition_key=user.id,
    )


@app.put("/api/v1/me/favourites/{listing_id}", status_code=204)
async def add_favourite(listing_id: str, user: User) -> None:
    await store["favourites"].upsert_item(
        {"id": f"{user.id}:{listing_id}", "userId": user.id, "listingId": listing_id, "createdAt": _now()}
    )


@app.delete("/api/v1/me/favourites/{listing_id}", status_code=204)
async def remove_favourite(listing_id: str, user: User) -> None:
    try:
        await store["favourites"].delete_item(item=f"{user.id}:{listing_id}", partition_key=user.id)
    except CosmosResourceNotFoundError:
        pass


# ─────────────────────────────── saved searches (FR-6.2) ───────────────────────────────
class SavedSearchIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    raw_query: str | None = Field(None, max_length=300)
    filters: dict = Field(default_factory=dict)


@app.get("/api/v1/me/saved-searches")
async def list_saved_searches(user: User) -> list[dict]:
    return await store.query(
        "saved-searches", "SELECT c.id, c.name, c.raw_query, c.filters, c.createdAt FROM c WHERE c.userId = @u",
        [{"name": "@u", "value": user.id}], partition_key=user.id,
    )


@app.post("/api/v1/me/saved-searches", status_code=201)
async def create_saved_search(body: SavedSearchIn, user: User) -> dict:
    item = {"id": uuid.uuid4().hex, "userId": user.id, **body.model_dump(), "createdAt": _now()}
    await store["saved-searches"].create_item(item)
    return item


@app.delete("/api/v1/me/saved-searches/{search_id}", status_code=204)
async def delete_saved_search(search_id: str, user: User) -> None:
    try:
        await store["saved-searches"].delete_item(item=search_id, partition_key=user.id)
    except CosmosResourceNotFoundError:
        pass
