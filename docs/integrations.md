# Integrations — top to bottom

> Every connection in EstateAI: what talks to what, over which protocol, with which configuration and
> credentials, where the code is, what happens when it fails, how it maps to Azure, and how to check it.
> Request-level walkthroughs: [api-tracing.md](api-tracing.md) · endpoint table: [api-reference.md](api-reference.md) ·
> design decisions: [decisions/](decisions/).

```
 ┌──────────────┐  HTTPS   ┌────────────┐  HTTP   ┌───────────────────────────────┐
 │ Browser      │ ───────▶ │ nginx/Vite │ ──────▶ │ Gateway (YARP, .NET 10) :8080 │ ──JWKS──▶ identity
 │ React SPA    │ ◀─fonts─ │ :3000/5173 │         │ auth · rate limit · cache ·   │ ──Redis──▶ rate limits, output cache,
 └──────────────┘ Google   └────────────┘         │ retries · circuit breakers    │            token revocation
                  Fonts                           └───────────────┬───────────────┘
                                   HTTP + JWT + X-Request-Id + traceparent │
      ┌──────────────┬──────────────┬─────────────────┼──────────────┬──────────────────┐
      ▼              ▼              ▼                 ▼              ▼                  │
  identity        listing        search              ai          engagement     notification (worker)
  Postgres        Postgres       Postgres+pgvector   Postgres+pgv  Cosmos DB       SMTP
  Redis, SMTP     Blob, Redis    Redis               Cosmos, Blob  Redis
                                                     Gemini API
      └──── internal HTTP (ResilientClient) ────┘   └──── Service Bus topics (outbox) ────┘
                         all services ──OTLP──▶ Aspire Dashboard / Application Insights
```

Legend for each section: **Direction** · **Protocol** · **Config** (env var → settings field) · **Code** ·
**Credentials** · **Failure behaviour** · **Azure** · **Check**.

---

## 1. Browser → web server → gateway

| | |
|---|---|
| Direction | Browser → nginx (`web` container, :3000) or Vite dev server (:5173) → gateway :8080 |
| Protocol | HTTPS in Azure / HTTP locally; same-origin `/api/*` calls; Server-Sent Events for Q&A |
| Config | `web/nginx.conf` (`location /api/` → `http://gateway:8080`, `proxy_buffering off`); `web/vite.config.ts` proxy |
| Code | `web/src/lib/api.ts` (all JSON calls), `web/src/lib/sse.ts` (streaming), `web/src/lib/auth.tsx` |
| Credentials | Access token (15 min) in **memory**, sent as `Authorization: Bearer`; refresh token as httpOnly cookie `estate_refresh` (path `/api/v1/auth`) |
| Failure behaviour | 401 → one silent refresh + retry (`refreshSession`); other errors surface the envelope's `message` in the UI |
| Azure | Azure Static Web Apps serves the SPA; `/api/*` goes to the gateway (linked backend or Front Door route) |
| Check | `curl localhost:3000/api/v1/search?limit=1` → 200 through nginx |

**Google Fonts:** `web/index.html` loads the Mukta font from `fonts.googleapis.com` / `fonts.gstatic.com`.
This is the only third-party call the browser makes. Self-host the font files if the privacy policy or CSP forbids it.

## 2. Gateway → services (YARP)

| | |
|---|---|
| Direction | Gateway → identity, listing, search, ai, engagement (clusters in `appsettings.json`) |
| Protocol | HTTP/1.1; forwards `Authorization`, `X-Request-Id`, `X-Forwarded-*`, W3C `traceparent` |
| Config | `services/gateway/src/Gateway/appsettings.json` → `ReverseProxy:Routes` (21 routes with policies) and `ReverseProxy:Clusters` (destinations). Override per environment with env vars, e.g. `ReverseProxy__Clusters__listing__Destinations__d1__Address` |
| Code | `Program.cs` (pipeline), `Infrastructure/Resilience.cs` (Polly + health report), `Middleware.cs` (errors, request id) |
| Credentials | None between gateway and services (private network); each service re-verifies the user's JWT |
| Failure behaviour | Active health checks (`/health/ready` every 10 s) and passive checks (transport failures) take destinations out; GET/HEAD retried twice; circuit breaker per upstream (≥ 50 % failures over ≥ 10 calls in 30 s → open 15 s); errors become 503/504 envelopes |
| Azure | Container Apps: gateway has external ingress; services have **internal** ingress (`http://listing` etc. inside the environment). Optionally Front Door / API Management in front |
| Check | `curl localhost:8080/health/deep` lists each cluster's active/passive health |

## 3. Gateway and services → identity (JWKS)

| | |
|---|---|
| Direction | Gateway and every Python service → identity `/.well-known/openid-configuration` and `/.well-known/jwks.json` |
| Protocol | HTTP GET, cached (gateway: JwtBearer metadata cache with refresh on unknown `kid`; Python: `PyJWKClient`, 5 min) |
| Config | Gateway `Jwt:MetadataAddress`, `Jwt:Issuer`, `Jwt:Audience`, `Jwt:RequireHttpsMetadata`; Python `JWT_ISSUER`, `JWT_AUDIENCE`, `IDENTITY_URL` (JWKS URL derived) |
| Code | `Infrastructure/EdgeAuthentication.cs`; `libs/common/estate_common/auth.py`; issuer side `services/identity/app/tokens.py` |
| Credentials | Public keys only. Private keys stay in identity (`signing_keys` table locally; Key Vault in Azure — T4.14) |
| Failure behaviour | Keys are cached; if JWKS is unreachable and a new `kid` appears, the gateway returns 401 and Python services 503 `dependency_unavailable` |
| Azure | Same (internal URL). If you move to Entra External ID, point both at Entra's metadata URL; no code change in verifiers |
| Check | `curl localhost:8001/.well-known/jwks.json` |

## 4. Service ↔ service (internal HTTP)

All calls use `estate_common.http.ResilientClient`: per-call timeout, retries with jittered backoff for idempotent calls only,
circuit breaker per dependency (5 consecutive failures → open 30 s → one trial call), forwards `X-Request-Id`.
Failures become `DependencyUnavailable` (503). `/internal/*` routes are never exposed by the gateway.

| Caller | Callee endpoint | Why | Retries | Code |
|---|---|---|---|---|
| search | ai `POST /internal/nl-parse` | Parse an NL query | none (2 s budget, falls back) | `services/search/app/ai_client.py` |
| search | ai `POST /internal/embeddings` | Embed queries and listings | yes (pure function) | same |
| ai | listing `GET /internal/listings/{id}/facts` | Fact sheet for Q&A / describe (cached) | yes | `services/ai/app/main.py` `fetch_facts` |
| engagement | listing `GET /internal/listings/{id}/summary` | Agent id + publish status for enquiries | yes | `services/engagement/app/main.py` |
| notification | identity `GET /internal/users/{id}` | Agent's email | yes | `services/notification/app/main.py` |
| notification | engagement `GET /internal/enquiries/{agent}/{id}` | Enquiry details (kept off the bus) | yes | same |
| listing (dev seed) | identity `GET /internal/users/by-email/{email}` | Owner of sample listings | yes | `services/listing/app/seed.py` |

Config: `IDENTITY_URL`, `LISTING_URL`, `SEARCH_URL`, `AI_URL`, `ENGAGEMENT_URL`, `HTTP_TIMEOUT_S`, `HTTP_RETRIES`,
`BREAKER_FAILURE_THRESHOLD`, `BREAKER_RESET_S`. Azure: Container Apps internal DNS names; restrict `/internal/*` further with
ingress IP restrictions or a service mesh if required.

## 5. Services → PostgreSQL (+ pgvector)

| Database | Owner | Tables | Notes |
|---|---|---|---|
| `identity` | identity | `users`, `signing_keys`, `refresh_tokens` | |
| `listing` | listing | `listings`, `listing_images`, `listing_documents`, `outbox` | source of truth for listings |
| `search` | search | `search_listings` (vector(768), generated tsvector, HNSW + GIN indexes) | projection; rebuildable via `/internal/dev/republish` |
| `ai` | ai | `document_chunks` (vector(768), HNSW), `outbox` | rebuildable from PDFs in Blob |

| | |
|---|---|
| Protocol | PostgreSQL wire protocol via SQLAlchemy 2 async + asyncpg |
| Config | `DATABASE_URL` per service (defaults in each `services/<svc>/app/config.py`; not set in the shared `.env`) |
| Code | `libs/common/estate_common/db.py`; models in `services/<svc>/app/models.py`; migrations in `services/<svc>/migrations/` |
| Credentials | Local `estate`/`estate`. Azure: Entra ID auth with the Container App's managed identity (token as password) or a Key Vault secret |
| Schema | Alembic: `alembic upgrade head` runs before each service starts locally; a Container Apps job in Azure. `init.sql` creates the four databases locally |
| Failure behaviour | `pool_pre_ping`; `/health/ready` fails → the gateway stops routing to that replica |
| Azure | Azure Database for PostgreSQL Flexible Server, `vector` extension allow-listed (`azure.extensions = VECTOR`) |
| Check | `docker compose exec postgres psql -U estate -d listing -c "select version_num from alembic_version"` |

## 6. Gateway and services → Redis

| User | Purpose | Keys |
|---|---|---|
| gateway | Rate limiting (sliding window, per user/IP), edge output cache, token revocation lookups | `rl:*`, `gw-oc:*`, `jwt:*` (read) |
| identity | OTP codes and attempts, writing revocations | `otp:*`, `otp_attempts:*`, `jwt:*` |
| all Python services | Revocation checks (`estate_common.auth`) | `jwt:*` (read) |
| listing, search, ai | Two-level cache L2 + invalidation pub/sub | `cache:*`, `cachever:*`, channel `cacheinv:*` |
| listing, engagement | Idempotency keys | `idem:*` |
| search | Parsed NL queries | `nl:*` |

| | |
|---|---|
| Config | Python `REDIS_URL`; gateway `Redis__ConnectionString` (StackExchange.Redis format) |
| Failure behaviour | Caches and idempotency **fail open** (work without Redis); revocation checks fail open (tokens live 15 min); gateway named rate limits **fail closed** (503) while the in-memory global limiter keeps the rest of the API up |
| Azure | Azure Managed Redis (or Azure Cache for Redis) with TLS (`rediss://`, port 10000/6380) and Entra auth or access key in Key Vault |
| Check | `docker compose exec redis redis-cli --scan --pattern 'cache:*' \| head` |

## 7. Services → Azure Cosmos DB (NoSQL)

| Database/container | Partition key | Owner | Contents |
|---|---|---|---|
| `estateai/enquiries` | `/agentId` | engagement | enquiries + `eventPublished` outbox flag |
| `estateai/favourites` | `/userId` | engagement | id `{user}:{listing}` |
| `estateai/saved-searches` | `/userId` | engagement | name, raw query, filters |
| `estateai/ai-requests` | `/feature` (TTL = `AI_LOG_RETENTION_DAYS`) | ai | one item per LLM call: model, prompt version, tokens, cost, latency, status, feedback |

| | |
|---|---|
| Protocol | HTTPS REST via `azure-cosmos` async SDK (`enable_endpoint_discovery=False` for the emulator) |
| Config | `COSMOS_ENDPOINT`, `COSMOS_KEY`, `COSMOS_DATABASE` |
| Code | `services/engagement/app/store.py`, `services/ai/app/telemetry_store.py` |
| Failure behaviour | engagement retries init for ~2.5 min at start and reports it in `/health/ready`; ai request logging never fails a user request |
| Azure | Azure Cosmos DB for NoSQL (serverless for MVP). Prefer Entra RBAC (`DefaultAzureCredential`) over keys — needs a small code change in both clients |
| Check | http://localhost:1234 (Data Explorer) |

## 8. listing and ai → Azure Blob Storage

| | |
|---|---|
| Direction | listing writes images and PDFs; listing serves images via `/api/v1/media/*`; ai reads PDFs for ingestion |
| Container | `listing-media` — `listings/{id}/images/{uuid}.webp`, `…_thumb.webp`, `listings/{id}/documents/{uuid}.pdf` |
| Config | `STORAGE_CONNECTION`, `MEDIA_CONTAINER` |
| Code | `services/listing/app/blob.py`, `services/ai/app/ingestion.py` |
| Failure behaviour | Upload errors return 500/503 to the agent; ingestion errors are retried by Service Bus then dead-lettered |
| Azure | Storage account, private container; managed identity with *Storage Blob Data Contributor* (listing) / *Reader* (ai); serve images via Front Door/CDN or SAS instead of proxying through the API |
| Check | Azure Storage Explorer → Local emulator → `listing-media` |

## 9. Services ↔ Azure Service Bus

| | |
|---|---|
| Topics / subscriptions | `listing-events` → `search`, `ai` · `ai-events` → `listing` · `engagement-events` → `notification` (see [api-tracing.md §5](api-tracing.md#5-service-bus-map)) |
| Protocol | AMQP 1.0 via `azure-servicebus` (async) |
| Envelope | `estate_common.events.Event`: `id` (= message id), `type`, `source`, `subject`, `time`, `data` (no PII), `correlation_id` |
| Publishing | listing and ai: **transactional outbox** (`estate_common.outbox`) + relay; engagement: publish + `eventPublished` flag + relay |
| Consuming | `estate_common.messaging.consume_forever`: reconnects forever, abandons on handler error (redelivery → dead-letter after `MaxDeliveryCount`), binds `correlation_id` for logs |
| Config | `SERVICEBUS_CONNECTION`; topology in `infra/local/servicebus/Config.json` (emulator limits: TTL ≤ 1 h, duplicate-detection window ≤ 5 min) |
| Azure | Service Bus **Standard** namespace (topics need Standard+). Set TTL (e.g. 14 days) and duplicate detection (e.g. 10 min) in IaC; managed identity with *Azure Service Bus Data Sender/Receiver* |
| Check | `select count(*) from outbox where published_at is null;` should be 0; consumer logs `event_handled` |

## 10. ai → Google Gemini API

| | |
|---|---|
| Direction | ai service only (ADR-0004/0013) → `generativelanguage.googleapis.com` |
| Calls | `generate_content` (JSON schema output: NL parse, descriptions), `generate_content_stream` (Q&A), `embed_content` (`gemini-embedding-001`, 768 dims, normalised) |
| Config | `AI_FAKE` (default `true` = offline), `GEMINI_API_KEY`, `AI_MODEL_SEARCH/DESCRIBE/QA/JUDGE`, `AI_TIMEOUT_*_S`, `AI_MAX_RETRIES`, `AI_PROMPT_VERSION_*`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIM` |
| Code | `services/ai/app/llm/gemini_client.py`, `services/ai/app/embeddings.py` (the only files that import `google.genai`) |
| Credentials | API key (Key Vault in Azure). Use a **paid-tier** key: free-tier prompts may be used by Google to improve products |
| Failure behaviour | Timeouts per feature; retries on 408/429/5xx; safety blocks → `AIRefused`; every AI feature has a non-AI fallback (NL search → keyword/vector search; Q&A → "ask the agent") |
| Azure | Outbound HTTPS from the ai Container App to Google; or switch to Vertex AI (`genai.Client(vertexai=True, …)`) |
| Check | `ai_requests` items in Cosmos show `model`, tokens and `status` for every call |

## 11. identity and notification → email (SMTP)

| | |
|---|---|
| Direction | identity (sign-in codes), notification (enquiry emails to agents) |
| Config | `SMTP_HOST`, `SMTP_PORT`, `EMAIL_FROM`, `WEB_BASE_URL` |
| Code | `services/identity/app/otp.py`, `services/notification/app/main.py` (`aiosmtplib`) |
| Local | Mailpit catches everything: http://localhost:8025 |
| Azure | Azure Communication Services Email (SMTP relay with Entra app credentials, or switch to the ACS Email SDK); verified sender domain |
| Failure behaviour | Sign-in code request fails with 500; notification failures abandon the message → retried → dead-lettered |

## 12. Everything → telemetry (OpenTelemetry)

| | |
|---|---|
| What | Traces from the gateway (ASP.NET Core + HttpClient) and every Python service (FastAPI + httpx). Health probes excluded |
| Config | `OTEL_EXPORTER_OTLP_ENDPOINT` (compose sets `http://aspire-dashboard:18889`) |
| Code | `services/gateway/src/Gateway/Program.cs`, `libs/common/estate_common/telemetry.py` |
| Logs | JSON to stdout: gateway (`AddJsonConsole`, request-id scope), Python (`structlog`, `request_id` bound per request/event) |
| Azure | Application Insights: Azure Monitor OpenTelemetry distro or OTLP via the Container Apps OpenTelemetry agent; logs to Log Analytics |
| Check | http://localhost:18888 → Traces → filter by path |

## 13. Configuration reference (by integration)

| Setting | Used by | Default (local) |
|---|---|---|
| `SERVICEBUS_CONNECTION` | all except gateway | emulator connection string |
| `STORAGE_CONNECTION`, `MEDIA_CONTAINER` | listing, ai | Azurite, `listing-media` |
| `COSMOS_ENDPOINT`, `COSMOS_KEY`, `COSMOS_DATABASE` | engagement, ai | emulator, `estateai` |
| `REDIS_URL` / `Redis__ConnectionString` | Python services / gateway | `redis://redis:6379/0` / `redis:6379` |
| `DATABASE_URL` | identity, listing, search, ai | per-service default in `config.py` |
| `JWT_ISSUER`, `JWT_AUDIENCE`, `ACCESS_TOKEN_TTL_S`, `REFRESH_TOKEN_TTL_S`, `SIGNING_KEY_ROTATION_DAYS` | identity (+ verifiers) | `estateai-identity`, `estateai`, 900, 2592000, 30 |
| `*_URL` (service URLs) | callers of internal APIs | `http://<service>:8000` |
| `HTTP_TIMEOUT_S`, `HTTP_RETRIES`, `BREAKER_*` | ResilientClient | 5, 2, 5, 30 |
| `AI_*`, `GEMINI_API_KEY`, `EMBEDDING_*` | ai (+ `EMBEDDING_DIM` in search) | offline mode |
| `SMTP_*`, `EMAIL_FROM`, `WEB_BASE_URL` | identity, notification | Mailpit |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | all | Aspire Dashboard |
| `RateLimits:*`, `Cors:Origins`, `Jwt:*`, `ReverseProxy:*` | gateway (`appsettings.json` / `__` env overrides) | see file |

The full, commented list lives in `.env.example`.
