"""AI service — the only service that calls LLM / embedding providers (ADR-0004, ADR-0008)."""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Literal

import redis.asyncio as redis
import structlog
from fastapi import Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, text

from estate_common.cache import TwoLevelCache
from estate_common.events import Event
from estate_common.http import ResilientClient
from estate_common.outbox import OutboxRelay
from sse_starlette.sse import EventSourceResponse

from app import guardrails
from app.config import settings
from app.dashboard import daily_metrics, to_eval_case
from app.embeddings import get_embedder
from app.features import describe, improve, nl_search, qa
from app.features.schemas import SearchFilters
from app.ingestion import DocumentIngestor
from app.llm.base import AIOutputInvalid, AIRefused, CallContext
from app.models import DocumentChunk
from app.telemetry_store import ai_log
from estate_common import events
from estate_common.app import create_app, postgres_check, redis_check
from estate_common.auth import Admin, Agent, OptionalUser
from estate_common.db import Database
from estate_common.errors import AIUnavailable, DependencyUnavailable, Forbidden, NotFound, ValidationFailed
from estate_common.flags import KNOWN_FLAGS, FeatureFlags
from estate_common.messaging import consume_forever

log = structlog.get_logger(__name__)
db = Database(settings.database_url)
redis_client = redis.from_url(settings.redis_url)
flags = FeatureFlags(redis_client, {
    "ai_describe": settings.feature_ai_describe, "ai_improve": settings.feature_ai_improve,
    "listing_qa": settings.feature_listing_qa, "nl_search": True,
})
relay = OutboxRelay(db, settings.servicebus_connection)
listing_http = ResilientClient("listing", settings.listing_url, settings=settings)
# Fact sheets are read on every Q&A turn: L1 30 s, L2 5 min, dropped when a listing event arrives.
facts_cache = TwoLevelCache(redis_client, "facts", l1_ttl_s=30, l2_ttl_s=300)
LISTING_CHANGES = {events.LISTING_PUBLISHED, events.LISTING_UPDATED, events.LISTING_UNPUBLISHED}


@asynccontextmanager
async def lifespan(_app):
    # Schema (incl. the pgvector extension) is managed by Alembic.
    await ai_log.init()
    ingestor = DocumentIngestor(db)

    async def on_listing_event(event: Event) -> None:
        if event.type == events.LISTING_DOCUMENT_UPLOADED:
            await ingestor.handle(event)
        elif event.type == events.LISTING_DOCUMENT_DELETED:
            async with db.sessionmaker() as session:  # idempotent: deleting twice deletes nothing
                await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == event.data["document_id"]))
                await session.commit()
        elif event.type in LISTING_CHANGES:
            await facts_cache.invalidate(event.subject)

    async def on_identity_event(event: Event) -> None:
        log.info("ai_requests_unlinked_from_deleted_user", count=await ai_log.forget_user(event.data["user_id"]))

    tasks = [
        asyncio.create_task(consume_forever(settings.servicebus_connection, events.LISTING_EVENTS, "ai", on_listing_event,
                                            handled_types={events.LISTING_DOCUMENT_UPLOADED, events.LISTING_DOCUMENT_DELETED,
                                                           *LISTING_CHANGES})),
        asyncio.create_task(consume_forever(settings.servicebus_connection, events.IDENTITY_EVENTS, "ai", on_identity_event,
                                            handled_types={events.USER_DELETED})),
        asyncio.create_task(relay.run_forever()),
        asyncio.create_task(facts_cache.listen_for_invalidations()),
    ]
    yield
    for task in tasks:
        task.cancel()
    await ai_log.close()
    await listing_http.aclose()


app = create_app(settings, title="AI Service", lifespan=lifespan,
                 readiness={"postgres": postgres_check(db), "redis": redis_check(redis_client)})


async def fetch_facts(listing_id: str) -> dict:
    async def load() -> dict | None:
        response = await listing_http.get(f"/internal/listings/{listing_id}/facts")
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise DependencyUnavailable("Listing details are temporarily unavailable.")
        return response.json()

    facts = await facts_cache.get_or_load(listing_id, load)
    if facts is None:
        raise NotFound("Listing not found.")
    return facts


# ─────────────────────────────── internal (called by search service) ───────────────────────────────
class ParseRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)


class ParseResponse(BaseModel):
    filters: SearchFilters
    ai_request_id: str


@app.post("/internal/nl-parse")
async def internal_nl_parse(body: ParseRequest) -> ParseResponse:
    try:
        filters, request_id = await nl_search.parse(body.query)
    except (AIRefused, AIOutputInvalid) as exc:
        raise AIUnavailable("Could not interpret the query.") from exc
    return ParseResponse(filters=filters, ai_request_id=request_id)


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=128)
    input_type: Literal["document", "query"] = "document"


@app.post("/internal/embeddings")
async def internal_embeddings(body: EmbedRequest) -> dict:
    embedder = get_embedder()
    return {"model": embedder.model, "vectors": await embedder.embed(body.texts, body.input_type)}


# ─────────────────────────────── describe (FR-4) ───────────────────────────────
class DescribeRequest(BaseModel):
    listing_id: str
    tone: Literal["professional", "warm", "luxury"] = "professional"
    length: Literal["short", "medium", "long"] = "medium"
    agent_notes: str = Field("", max_length=2000)


class DescribeResponse(BaseModel):
    title: str
    description: str
    highlights: list[str]
    warnings: list[str]
    ai_request_id: str


@app.post("/api/v1/ai/describe")
async def ai_describe(body: DescribeRequest, user: Agent) -> DescribeResponse:
    if not await flags.is_enabled("ai_describe"):
        raise NotFound("This feature is not enabled.")
    facts = await fetch_facts(body.listing_id)
    if facts["agent_id"] != user.id and not user.is_admin:
        raise Forbidden("You can only generate descriptions for your own listings.")
    ctx = CallContext(feature="describe", user_id=user.id, listing_id=body.listing_id)
    try:
        result = await describe.generate(facts, body.tone, body.length, body.agent_notes, ctx)
    except AIRefused as exc:
        raise ValidationFailed("The assistant couldn't write a description for this input.") from exc
    except AIOutputInvalid as exc:
        raise AIUnavailable("The assistant returned an unusable draft. Please try again.") from exc
    return DescribeResponse(**result.output.model_dump(), warnings=result.warnings, ai_request_id=result.request_id)


# ─────────────────────────────── listing Q&A (FR-5) ───────────────────────────────
class QARequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    history: list[dict] = Field(default_factory=list, max_length=12)


@app.post("/api/v1/listings/{listing_id}/qa")
async def listing_qa(listing_id: str, body: QARequest, user: OptionalUser, request: Request) -> EventSourceResponse:
    if not await flags.is_enabled("listing_qa"):
        raise NotFound("This feature is not enabled.")
    facts = await fetch_facts(listing_id)
    if facts["status"] != "published" and not (user and (user.is_admin or user.id == facts["agent_id"])):
        raise NotFound("Listing not found.")
    ctx = CallContext(feature="qa", user_id=user.id if user else None, listing_id=listing_id)

    async def events_stream():
        async for event in qa.answer(db, facts, body.question, body.history, ctx):
            if await request.is_disconnected():  # stop spending tokens if the user left
                break
            yield event

    return EventSourceResponse(events_stream(), headers={"X-Accel-Buffering": "no"})


@app.get("/api/v1/listings/{listing_id}/qa/suggestions")
async def qa_suggestions(listing_id: str) -> dict:
    facts = await fetch_facts(listing_id)
    async with db.sessionmaker() as session:
        has_docs = bool(await session.scalar(
            text("SELECT 1 FROM document_chunks WHERE listing_id = :id LIMIT 1"), {"id": listing_id}
        ))
    return {"suggestions": qa.suggestions(facts["facts"], has_docs)}


# ─────────────────────────────── feedback (FR-5.6) ───────────────────────────────
class FeedbackRequest(BaseModel):
    ai_request_id: str = Field(pattern=r"^(nl_search|describe|improve|qa)\.[0-9a-f]{32}$")
    rating: Literal[-1, 1]
    comment: str | None = Field(None, max_length=1000)


@app.post("/api/v1/ai/feedback")
async def ai_feedback(body: FeedbackRequest) -> dict:
    return {"recorded": await ai_log.set_feedback(body.ai_request_id, body.rating, body.comment)}


# ─────────────────────────────── improve my text (FR-4.4) ───────────────────────────────
class ImproveRequest(BaseModel):
    listing_id: str
    text: str = Field(min_length=20, max_length=5000)
    tone: Literal["professional", "warm", "luxury"] = "professional"


class ImproveResponse(BaseModel):
    description: str
    warnings: list[str]
    ai_request_id: str


@app.post("/api/v1/ai/improve")
async def ai_improve(body: ImproveRequest, user: Agent) -> ImproveResponse:
    if not await flags.is_enabled("ai_improve"):
        raise NotFound("This feature is not enabled.")
    facts = await fetch_facts(body.listing_id)
    if facts["agent_id"] != user.id and not user.is_admin:
        raise Forbidden("You can only rewrite descriptions for your own listings.")
    ctx = CallContext(feature="improve", user_id=user.id, listing_id=body.listing_id)
    try:
        result = await improve.rewrite(facts, body.text, body.tone, ctx)
    except AIRefused as exc:
        raise ValidationFailed("The assistant couldn't rewrite this text.") from exc
    except AIOutputInvalid as exc:
        raise AIUnavailable("The assistant returned an unusable rewrite. Please try again.") from exc
    return ImproveResponse(description=result.output.description, warnings=result.warnings, ai_request_id=result.request_id)


@app.get("/api/v1/ai/features")
async def ai_features() -> dict:
    """Which AI features are switched on (FR-7.4), so the UI hides what is off instead of showing errors."""
    return {name: await flags.is_enabled(name) for name in KNOWN_FLAGS}


# ─────────────────────────────── guardrails for other services ───────────────────────────────
class ListingTextCheck(BaseModel):
    fields: dict[str, str] = Field(max_length=10)


@app.post("/internal/guardrails/listing-text")
async def internal_listing_text_check(body: ListingTextCheck) -> dict:
    """Deterministic fair-housing check (requirements §7) for agent-written listing text. No LLM call."""
    violations = [
        {"field": field, "phrase": sentence[:200]}
        for field, value in body.fields.items()
        for sentence in guardrails.fair_housing_violations(value[:10_000])
    ]
    return {"violations": violations}


# ─────────────────────────────── admin AI dashboard (FR-7.2, 7.3, 7.4) ───────────────────────────────
@app.get("/api/v1/admin/ai/metrics")
async def admin_ai_metrics(_admin: Admin, days: int = Query(14, ge=1, le=30)) -> dict:
    """Per feature per day: requests, tokens, cost, latency p50/p95, error rate, 👍/👎."""
    rows = daily_metrics(await ai_log.recent(days))
    return {"days": days, "logging_enabled": ai_log.enabled, "rows": rows}


@app.get("/api/v1/admin/ai/feedback")
async def admin_ai_feedback(
    _admin: Admin,
    rating: Literal[-1, 1] = -1,
    feature: Literal["nl_search", "describe", "improve", "qa"] | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[dict]:
    """Rated interactions, newest first. Request and response text were PII-redacted when logged."""
    fields = ("id", "feature", "created_at", "listing_id", "prompt_id", "prompt_version", "model", "status",
              "request_redacted", "response_redacted", "feedback", "feedback_comment")
    return [{k: row.get(k) for k in fields} for row in await ai_log.with_feedback(rating, feature, limit)]


@app.get("/api/v1/admin/ai/feedback/export")
async def admin_ai_feedback_export(
    _admin: Admin, feature: Literal["nl_search", "describe", "improve", "qa"] | None = None,
) -> Response:
    """👎 interactions as candidate eval cases, one JSON object per line (docs/ai/evals.md §8)."""
    rows = await ai_log.with_feedback(-1, feature, 1000)
    body = "".join(json.dumps(to_eval_case(row), ensure_ascii=False) + "\n" for row in rows)
    return Response(content=body, media_type="application/x-ndjson", headers={
        "Content-Disposition": f"attachment; filename=\"eval-candidates-{feature or 'all'}.jsonl\"",
        "Cache-Control": "no-store",
    })


class FlagUpdate(BaseModel):
    enabled: bool | None = Field(description="null resets the flag to the service's configured default")


@app.get("/api/v1/admin/ai/flags")
async def admin_flags(_admin: Admin) -> dict:
    return await flags.snapshot()


@app.put("/api/v1/admin/ai/flags/{name}")
async def admin_set_flag(name: str, body: FlagUpdate, _admin: Admin) -> dict:
    if name not in KNOWN_FLAGS:
        raise NotFound("Unknown feature flag.")
    if body.enabled is None:
        await flags.reset(name)
    else:
        await flags.set(name, body.enabled)
    log.info("feature_flag_changed", flag=name, enabled=body.enabled)
    return (await flags.snapshot())[name]
