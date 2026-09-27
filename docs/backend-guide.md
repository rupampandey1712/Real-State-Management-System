# Backend guide — FastAPI services

> Everything needed to read, change and extend the Python services: layout, request lifecycle, the shared
> library, auth, errors, data and migrations, events, resilience, caching, AI code, testing, and step-by-step
> recipes. Rules for AI coding agents are in [../CLAUDE.md](../CLAUDE.md); endpoint facts in [api-reference.md](api-reference.md).

**Stack:** Python 3.12 · FastAPI · Pydantic v2 · pydantic-settings · SQLAlchemy 2 (async) + asyncpg · Alembic ·
redis-py (asyncio) · azure-servicebus / azure-cosmos / azure-storage-blob (async) · httpx · structlog · OpenTelemetry ·
google-genai (ai only) · pytest + pytest-asyncio + fakeredis.

---

## 1. Repository layout

```
libs/common/estate_common/        shared, cross-cutting only — no domain logic
  settings.py      CommonSettings (env-driven) every service extends
  app.py           create_app(): logging, error handling, telemetry, /health, /health/ready
  errors.py        DomainError hierarchy, error envelope, request-id middleware + access log
  auth.py          JWT verification (RS256 via JWKS), revocation, User/Agent/Admin dependencies
  db.py            Base (DeclarativeBase), Database (engine + session dependency)
  migrations.py    shared Alembic runner used by each service's migrations/env.py
  events.py        Event envelope, topic and event-type constants
  messaging.py     EventPublisher (direct), consume_forever (subscription consumer)
  outbox.py        OutboxMessage table, add_event(), OutboxRelay
  http.py          ResilientClient (timeouts, retries, circuit breaker, request-id propagation)
  cache.py         TwoLevelCache (in-process L1 + Redis L2, pub/sub invalidation)
  idempotency.py   IdempotencyMiddleware (Idempotency-Key)
  logging.py       structlog JSON configuration
  telemetry.py     OpenTelemetry (FastAPI + httpx instrumentation, OTLP exporter)

services/<svc>/
  app/main.py      FastAPI app, lifespan (background tasks), route handlers
  app/config.py    <Svc>Settings(CommonSettings) — every setting the service reads
  app/models.py    SQLAlchemy models (Postgres services)
  app/schemas.py   Pydantic request/response models (where there are many)
  app/...          domain modules (listing: mapping, money, images, blob, seed; ai: llm/, prompts/, features/ …)
  migrations/      Alembic (Postgres services): env.py, script.py.mako, versions/
  alembic.ini
  tests/           pytest (pytest.ini adds ../../libs/common and . to the path)
  Dockerfile       build context = repo root; PYTHONPATH=/libs/common:/app
  requirements.txt service-specific deps (libs/common/requirements.txt is installed too)
```

| Service | Port | Owns | Background tasks started in `lifespan` |
|---|---|---|---|
| identity | 8001 | users, signing keys, refresh tokens (Postgres), OTP (Redis) | — (loads keys, seeds dev users) |
| listing | 8002 | listings, images, documents, outbox (Postgres), media (Blob) | ai-events consumer, OutboxRelay, cache invalidation listener |
| search | 8003 | search projection (Postgres + pgvector) | listing-events consumer, cache listener |
| ai | 8004 | document chunks, outbox (Postgres), AI request log (Cosmos) | listing-events consumer (ingestion + fact-cache invalidation), OutboxRelay, cache listener |
| engagement | 8005 | enquiries, favourites, saved searches (Cosmos) | enquiry event relay |
| notification | — | nothing (worker) | engagement-events consumer |

## 2. Request lifecycle inside a service

```
uvicorn → FastAPI
  ├─ OpenTelemetry middleware          span from incoming `traceparent`
  ├─ IdempotencyMiddleware             (listing, engagement; only configured POST paths)
  ├─ request_id_middleware             bind request_id, time the request, log {"event": "request", ...}
  ├─ route matching + dependencies     Session (DB), User/Agent/Admin (JWT), body → Pydantic model
  ├─ handler                           domain logic; raise DomainError subclasses for expected failures
  └─ exception handlers                DomainError → envelope; RequestValidationError → 422; anything else → 500 "internal"
```
Middleware added later with `app.add_middleware` wraps the outside, so `IdempotencyMiddleware` runs before the
request-id middleware; it reads `request.state.request_id` defensively.

## 3. The app factory and settings

Every HTTP service is created the same way (`services/listing/app/main.py`):

```python
db = Database(settings.database_url)
cache_redis = redis.from_url(settings.redis_url)
listing_cache = TwoLevelCache(cache_redis, "listing", l1_ttl_s=10, l2_ttl_s=300)
relay = OutboxRelay(db, settings.servicebus_connection)

@asynccontextmanager
async def lifespan(_app):
    await blobs.ensure_container()
    tasks = [
        asyncio.create_task(consume_forever(settings.servicebus_connection, events.AI_EVENTS, "listing",
                                            on_document_processed, handled_types={events.DOCUMENT_PROCESSED})),
        asyncio.create_task(relay.run_forever()),
        asyncio.create_task(listing_cache.listen_for_invalidations()),
    ]
    yield
    for task in tasks:
        task.cancel()

app = create_app(settings, title="Listing Service", lifespan=lifespan,
                 readiness={"postgres": postgres_check(db), "redis": redis_check(cache_redis)})
app.add_middleware(IdempotencyMiddleware, client=cache_redis, service="listing", paths=[r"/api/v1/listings"])
```

`create_app` (`estate_common/app.py`) gives every service: JSON logging, the error envelope, request ids,
OpenTelemetry, `GET /health` (liveness) and `GET /health/ready` (runs each readiness check with a 2 s timeout;
503 with details if any fails — the gateway's active health checks use it). Swagger UI at `/docs` only when `APP_ENV=local`.

**Settings** are pydantic-settings classes. Environment variables map case-insensitively to fields
(`REDIS_URL` → `redis_url`); `.env` is read too. Never read `os.environ` in feature code — add a field instead.

```python
class ListingSettings(CommonSettings):          # services/listing/app/config.py
    database_url: str = "postgresql+asyncpg://estate:estate@postgres:5432/listing"
    storage_connection: str = ""
    max_image_mb: int = 15

settings = ListingSettings(service_name="listing")
```

## 4. Authentication and authorization

Tokens are **RS256** JWTs signed only by identity; everything else verifies with public keys from
`identity /.well-known/jwks.json` (ADR-0015). `estate_common.auth` provides typed dependencies:

| Dependency | Gives you | Fails with |
|---|---|---|
| `OptionalUser` | `CurrentUser \| None` | 401 only if a token is sent and invalid |
| `User` | `CurrentUser` | 401 if missing/invalid/revoked |
| `Agent` | `CurrentUser` with role agent or admin | 401 / 403 |
| `Admin` | `CurrentUser` with role admin | 401 / 403 |

```python
@app.patch("/api/v1/listings/{listing_id}")
async def update_listing(listing_id: uuid.UUID, body: ListingUpdate, user: Agent, session: Session) -> ListingOut:
    listing = await _get(session, listing_id)
    _ensure_owner(listing, user)          # ownership is always checked in the handler/service
```

`decode_token` checks signature, algorithm (RS256 only — no algorithm confusion), `iss`, `aud`, `exp` (30 s leeway),
required claims, then the Redis revocation list (`jwt:deny:{jti}`, `jwt:revoked_before:{sub}`). The gateway also enforces
route policies, but **services never rely on the gateway alone**. `CurrentUser` has `id`, `role`, `agent_verified`, `jti`, `expires_at`.

Tests inject keys with `auth.set_key_resolver(lambda token: public_key)` and monkeypatch `auth.revocation_store`.

## 5. Errors — one envelope everywhere

Raise, don't return, for expected failures:

| Exception | HTTP | `code` |
|---|---|---|
| `ValidationFailed(message, details)` | 422 | `validation_error` |
| `Unauthorized` | 401 | `unauthorized` |
| `Forbidden` | 403 | `forbidden` |
| `NotFound` | 404 | `not_found` |
| `Conflict` | 409 | `conflict` |
| `AIUnavailable` | 503 (+ `Retry-After`) | `ai_unavailable` |
| `DependencyUnavailable` | 503 (+ `Retry-After`) | `dependency_unavailable` |

Response body: `{"error": {"code", "message", "details": [{"field", "issue"}], "request_id"}}`. Pydantic validation errors
are converted to the same shape. Any other exception is logged with a traceback and returned as `500 internal` with a
generic message — never leak exception text. Messages are user-facing: say what happened and what to do.

## 6. Request and response models

- Pydantic v2 models; `Field` constraints do input validation (`min_length`, `ge`, `pattern`); `model_validator` for
  cross-field rules (e.g. carpet area ≤ built-up area in `services/listing/app/schemas.py`).
- `ListingUpdate` uses `model_config = {"extra": "forbid"}` and `model_dump(exclude_unset=True)` for partial updates,
  then re-validates the merged result against `ListingFields`.
- Return type annotations **are** the response schema (FastAPI builds OpenAPI from them) — keep them precise.
- **Money:** store integer paise (`price_minor`); APIs accept rupees (`price_inr`) and return
  `{"amount_minor", "currency", "display"}` (`services/listing/app/money.py`). Never floats.
- IDs are UUIDs; timestamps are timezone-aware UTC.

## 7. Data access and migrations

```python
db = Database(settings.database_url)                      # async engine, pool_pre_ping
Session = Annotated[AsyncSession, Depends(db.session)]    # one session per request

async def handler(session: Session):
    listing = await session.get(Listing, listing_id)
    session.add(obj); await session.commit()
```
Background tasks open their own sessions: `async with db.sessionmaker() as session:`.

**Models** use SQLAlchemy 2 typed mappings (`Mapped[...] = mapped_column(...)`) on the shared `Base`.
Use Postgres dialect types where behaviour differs: **`sqlalchemy.dialects.postgresql.ARRAY`** (the generic `ARRAY`
has no `.contains()` — this caused a real 500 on amenity filters), `JSONB`, `UUID(as_uuid=True)`, `TSVECTOR`,
and `pgvector.sqlalchemy.Vector(dim)`.

**Migrations (Alembic) — never `create_all`:**
```bash
cd services/listing
export PYTHONPATH="../../libs/common:."         # Windows (Git Bash): "../../libs/common;."
alembic revision --autogenerate -m "add listing views"   # needs a reachable DATABASE_URL (docker compose up postgres)
# review the generated file in migrations/versions/ — autogenerate misses some things (see below)
alembic upgrade head
alembic upgrade head --sql                      # offline: print the SQL without a database
```
Review checklist for generated migrations: extension creation (`CREATE EXTENSION IF NOT EXISTS vector`),
`postgresql_using`/`postgresql_ops` on HNSW/GIN indexes, `sa.Computed` columns, server defaults, and data backfills.
In compose, migrations run before uvicorn starts; in Azure they run as a Container Apps job (see azure-deployment.md).

## 8. Events (Service Bus)

**Publishing from a Postgres service — always through the outbox**, inside the same transaction as the change:
```python
from estate_common.outbox import add_event

listing.status = "published"
add_event(session, topic=events.LISTING_EVENTS, event_type=events.LISTING_PUBLISHED,
          subject=str(listing.id), data=to_snapshot(listing), source="listing")
await session.commit()          # event is stored atomically with the state change
```
`OutboxRelay.run_forever()` (started in `lifespan`) publishes pending rows in batches with `FOR UPDATE SKIP LOCKED`
(safe with several replicas), marks them `published_at`, and backs off when Service Bus is down. The event id is the
message id, and topics have duplicate detection, so relay retries don't duplicate messages.

**Cosmos-backed services** (engagement) use `EventPublisher.publish(..., event_id=stable_id)` plus a flag on the
document and a relay that republishes unsent documents.

**Consuming:**
```python
asyncio.create_task(consume_forever(settings.servicebus_connection, events.LISTING_EVENTS, "search",
                                    on_listing_event, handled_types={events.LISTING_PUBLISHED, ...}))
```
Rules: handlers must be **idempotent** (upsert by id, delete-then-insert, overwrite status); raise on transient
failure (the message is abandoned → redelivered → dead-lettered after `MaxDeliveryCount`); events carry **no PII**
(fetch details over internal HTTP). The consumer binds the event's `correlation_id` as `request_id` in logs.

Adding a new event type: constant in `estate_common/events.py` → topic/subscription in
`infra/local/servicebus/Config.json` (respect emulator limits: TTL ≤ `PT1H`, duplicate window ≤ `PT5M`) and in Azure IaC →
row in `docs/architecture.md §4` and `docs/api-tracing.md §5`.

## 9. Calling another service

```python
listing_http = ResilientClient("listing", settings.listing_url, settings=settings)

response = await listing_http.get(f"/internal/listings/{listing_id}/facts")        # GET: retried
response = await ai_http.post("/internal/embeddings", json=..., idempotent=True)    # pure POST: retried
response = await ai_http.post("/internal/nl-parse", json=..., idempotent=False)     # not retried
if response.status_code == 404: raise NotFound(...)
if response.status_code >= 400: raise DependencyUnavailable(...)
```
Transport errors and 502/503/504 count as failures; 4xx are returned to you. After 5 consecutive failures the
breaker opens for 30 s and calls fail fast with `DependencyUnavailable`. The client forwards the current `X-Request-Id`.
Never use a bare `httpx.AsyncClient` for service calls. Internal endpoints live under `/internal/*` and are never routed
by the gateway.

## 10. Caching

```python
listing_cache = TwoLevelCache(cache_redis, "listing", l1_ttl_s=10, l2_ttl_s=300)

data = await listing_cache.get_or_load(str(listing_id), load_published)   # L1 → L2 → loader (single-flight)
await listing_cache.invalidate(str(listing_id))                            # after a write; broadcast to replicas
await search_cache.bump_version()                                          # versioned namespaces: drop everything
```
Values must be JSON-serialisable (`model_dump(mode="json")`); a loader returning `None` is not cached. Redis failures
make the cache step aside (the loader runs) — never an error. Start `listen_for_invalidations()` in `lifespan` so other
replicas drop their L1 entries. Current namespaces: `listing` (detail), `search` (classic results, versioned), `facts` (ai).

## 11. Idempotency keys

```python
app.add_middleware(IdempotencyMiddleware, client=redis_client, service="engagement",
                   paths=[r"/api/v1/listings/[^/]+/enquiries", r"/api/v1/me/saved-searches"])
```
For listed POST paths with an `Idempotency-Key` header: first request is stored (status < 500) for 24 h; a repeat with
the same body replays it (`Idempotent-Replayed: true`); same key, different body → 422; concurrent repeat → 409.
The frontend sends one key per form instance (`newIdempotencyKey()` in `web/src/lib/api.ts`).

## 12. Logging and tracing

- `structlog` JSON to stdout. `log = structlog.get_logger(__name__)`; log **events with fields**, not sentences:
  `log.info("document_ingested", document_id=..., chunks=12)`.
- `request_id` (and for consumers `event_type`, `event_id`) are bound automatically.
- Never log secrets, tokens, email addresses, phone numbers or raw prompts; AI payloads go through `redact_pii`.
- Azure SDK request/response header logging is silenced to WARNING in `configure_logging`.
- OpenTelemetry spans are automatic for FastAPI and httpx. Add custom spans only for expensive non-HTTP work.
See [api-tracing.md](api-tracing.md) for using request ids and traces.

## 13. The AI service (extra rules)

- Only `app/llm/gemini_client.py` and `app/embeddings.py` import `google.genai`. Features call `get_llm()` / `get_embedder()`.
- Prompts are versioned files `app/prompts/<id>.v<N>.md` (YAML front-matter + `# System` / `# User`, Jinja2 with
  `StrictUndefined`, `| untrusted` for any user-supplied value). Active version from `AI_PROMPT_VERSION_<ID>`.
- Structured output: Pydantic model → `response_json_schema` → `Model.model_validate_json(response.text)`.
  Keep output models flat, all fields required-but-nullable.
- `AI_FAKE=true` (default) uses `FakeLLMClient` and hashing embeddings: deterministic, offline, used by tests.
- Every call is logged to Cosmos `ai-requests` (tokens incl. thinking and cached, cost, latency, status).
- Guardrails (`app/guardrails.py`) run before and after the model. Details: [ai/](ai/).

## 14. Testing

| Kind | Where | Tools | Run |
|---|---|---|---|
| Unit (pure logic) | `services/*/tests`, `libs/common/tests` | pytest, pytest-asyncio (`asyncio_mode = auto`) | `pytest -q` in the folder |
| Redis-backed code | `libs/common/tests/test_cache.py`, `test_idempotency.py`, `test_auth.py` | `fakeredis.FakeAsyncRedis` | same |
| HTTP clients | `test_http_resilience.py` | `httpx.MockTransport` | same |
| FastAPI middleware | `test_idempotency.py` | `fastapi.testclient.TestClient` | same |
| LLM client | `services/ai/tests/test_gemini_client.py` | fake `client.aio.models` object | same |
| Gateway | `services/gateway/tests` | xUnit + `WebApplicationFactory` + a real Kestrel upstream | `dotnet test` |
| End to end | `scripts/smoke_test.py` | httpx against the running stack | `python scripts/smoke_test.py` |
| Contract | `scripts/check_api_sync.py` | static analysis of backend, gateway, web | `python scripts/check_api_sync.py` |

Patterns: inject dependencies (clients, sessions, resolvers) so tests can replace them; never call the real Gemini
API in unit tests; for DB-heavy logic prefer a small fake session object (see `services/identity/tests/test_tokens.py`)
or the running stack via the smoke test.

## 15. Recipes

### Add an endpoint (full slice)
1. Find the task and requirement (`docs/tasks.md`, `docs/requirements.md`).
2. Add request/response models (Pydantic) and the handler in the owning service's `main.py`; use `Session`,
   `User`/`Agent`/`Admin`, raise `DomainError`s; check ownership.
3. Side effects: DB write + `add_event` (if other services care) in one transaction; invalidate caches.
4. If users can double-submit it: add the path to the service's `IdempotencyMiddleware`.
5. **Gateway:** add a route in `services/gateway/src/Gateway/appsettings.json` with `AuthorizationPolicy`,
   `RateLimiterPolicy`, `OutputCachePolicy` (anonymous GETs only) and `TimeoutPolicy` as needed; add a gateway test if it has a policy.
6. **Frontend:** call it through `web/src/lib/api.ts` (types in `lib/types.ts`), with loading/empty/error states.
7. Tests; then `python scripts/check_api_sync.py` (must be IN SYNC) and `python scripts/gen_api_reference.py`.
8. Update `docs/design.md §3`, `docs/api-tracing.md` if it's a new flow, and tick the task.

### Add a table or column
Change `models.py` → `alembic revision --autogenerate -m "..."` → review → `alembic upgrade head` → tests.

### Add an event
See §8. Remember: idempotent consumer, no PII, topology in `Config.json` + IaC, docs.

### Add a new service
Copy the smallest similar service (`engagement` for Cosmos, `search` for Postgres): `app/config.py`, `app/main.py` with
`create_app(...)`, `requirements.txt`, `Dockerfile`, `pytest.ini`, `migrations/` if Postgres; add it to `docker-compose.yml`,
a gateway cluster + routes, `docs/architecture.md §2–4`, an ADR if it changes boundaries.

## 16. Pitfalls we hit (and how to avoid them)

| Pitfall | Symptom | Rule |
|---|---|---|
| Generic `sqlalchemy.ARRAY` | `NotImplementedError: ARRAY.contains()` → 500 on amenity filters | Use `sqlalchemy.dialects.postgresql.ARRAY` |
| Reserved email domains (`.local`, `.test`) | 422 on sign-in | Use real or `example.com` addresses in fixtures |
| Publishing after commit | Lost events if the process dies | `add_event` before commit (outbox) |
| Service Bus emulator limits | Emulator exits at start | TTL ≤ 1 h, duplicate window ≤ 5 min locally |
| Checking the cache after the DB read | Cache never helps | Anonymous paths go to the cache first (see `get_listing`) |
| Money in floats | Rounding errors | Integer paise |
| Blocking calls in async handlers | Latency spikes | CPU/blocking work → `run_in_threadpool` (e.g. Pillow, pypdf) |
