# Architecture — EstateAI Microservices on Azure

> Status: v1.0 · Last updated: 2026-09-27
> Decisions: [ADR-0008](decisions/0008-microservices-on-azure.md) (microservices) ·
> [0009](decisions/0009-react-spa-and-auth.md) (React SPA + auth) ·
> [0010](decisions/0010-azure-emulators-local-dev.md) (emulators) ·
> [0011](decisions/0011-service-bus-events.md) (events) ·
> [0012](decisions/0012-cosmos-db-engagement-and-ai-logs.md) (Cosmos DB)
> Feature-level design (data model, AI pipelines, guardrails) remains in [design.md](design.md).

---

## 1. System context

```
                         ┌────────────────────────────────────────┐
  Browser (React SPA) ──▶│ gateway  :8080   (public entry point)  │  CORS · rate limits · routing · SSE pass-through
                         └──┬──────┬───────┬───────┬───────┬──────┘
                 HTTP (JWT) │      │       │       │       │
          ┌─────────────────┘      │       │       │       └──────────────────┐
          ▼                        ▼       ▼       ▼                          ▼
   ┌────────────┐  ┌──────────────┐ ┌────────────┐ ┌─────────────────┐ ┌──────────────┐
   │ identity   │  │ listing      │ │ search     │ │ ai              │ │ engagement   │
   │ users/OTP  │  │ CRUD, media, │ │ read model,│ │ Gemini gateway, │ │ enquiries,   │
   │ JWT issue  │  │ documents    │ │ hybrid rank│ │ embeddings, RAG │ │ favourites,  │
   └─────┬──────┘  └──┬───────┬───┘ └──┬─────▲───┘ └──┬──────┬────▲──┘ │ saved search │
         │            │       │        │     │ HTTP    │      │    │    └──┬───────────┘
   Postgres(identity) │  Blob Storage  │     └─────────┘      │  Gemini API│
   Redis (OTP)   Postgres(listing)  Postgres(search)   Postgres(ai)   API  Cosmos DB
                      │                 + Redis cache   + Cosmos (AI logs)
                      │
   ═══════════════════╪════════════ Azure Service Bus (topics) ════════════════════════
     listing-events ──┴──▶ search (index) , ai (ingest documents)
     ai-events ──────────▶ listing (document status)
     engagement-events ──▶ notification ──▶ Email (Mailpit locally / Azure Communication Services)

   All services ──OTLP──▶ Aspire Dashboard (local) / Application Insights (Azure)
```

## 2. Service catalogue

| Service | Port (local) | Responsibility | Owns data | Talks to | Code |
|---|---|---|---|---|---|
| **gateway** | 8080 | **YARP on .NET 10** (ADR-0014): route table with per-route auth, rate-limit, output-cache and timeout policies; JWT (RS256/JWKS) + revocation at the edge; Redis sliding-window limits per user/IP; Redis output cache; Polly retries + circuit breakers; active/passive health checks; error envelope; blocks `/internal/*`; streams SSE | rate-limit counters, output cache | all HTTP services | `services/gateway` (C#) |
| **identity** | 8001 | Sign-in (email code, magic link, Google — ADR-0017), JWT issue, roles, agent applications, suspension, account deletion + 30-day purge, admin audit log | `users`, `admin_actions`, `outbox` (Postgres `identity`), OTP + magic tokens (Redis) | Mailpit/ACS, Google JWKS, Service Bus | `services/identity` |
| **listing** | 8002 | Listing aggregate: CRUD, status transitions (incl. archive, admin takedown/restore, suspension), duplicate, image processing + reorder, document upload/download/delete, publish checks, fact sheet | `listings`, `listing_images`, `listing_documents`, `moderation_actions` (Postgres `listing`), media (Blob) | Service Bus, identity (seed), ai (fair-housing check) | `services/listing` |
| **search** | 8003 | Search read model (projection), classic filters + sort + map area (`bbox`), NL hybrid search with `near` POIs (ADR-0018), query cache | `search_listings` + vectors (Postgres `search`), POI list (bundled CSV), Redis cache | ai (parse, embed) | `services/search` |
| **ai** | 8004 | **Only** caller of the Gemini API (generation + embeddings); prompts, guardrails (also `/internal/guardrails/listing-text` for listing), describe, improve, Q&A (RAG), document ingestion, AI telemetry & feedback, admin AI dashboard, runtime flags (ADR-0019) | `document_chunks` + vectors (Postgres `ai`), `ai-requests` (Cosmos) | Gemini API, listing (facts), Blob | `services/ai` |
| **engagement** | 8005 | Enquiries (with consent), favourites, saved searches; erasure on account deletion; 2-year enquiry retention | Cosmos containers `enquiries`, `favourites`, `saved-searches` | listing (summary), Service Bus | `services/engagement` |
| **notification** | — | Worker: emails agents on new enquiries | none | identity, engagement (internal), SMTP | `services/notification` |
| **web** | 3000 (nginx) / 5173 (vite dev) | React SPA | browser storage only | gateway | `web/` |

**Shared library** `libs/common/estate_common`: settings, logging, error envelope, JWT auth,
event envelope, Service Bus helpers, OpenTelemetry, DB helpers. No domain logic.

## 3. Data ownership

| Store | Database / container | Owner | Notes |
|---|---|---|---|
| PostgreSQL | `identity` | identity | users, roles, agent applications, admin audit log, outbox |
| PostgreSQL | `listing` | listing | source of truth for listings |
| PostgreSQL + pgvector | `search` | search | **projection** — rebuildable from events (`listing` re-publish) |
| PostgreSQL + pgvector | `ai` | ai | document chunks — rebuildable from PDFs in Blob |
| Blob Storage | `listing-media` | listing (write), ai (read documents) | images public via gateway `/api/v1/media/*`; documents never public |
| Cosmos DB | `estateai/enquiries` (pk `/agentId`) | engagement | |
| Cosmos DB | `estateai/favourites`, `saved-searches` (pk `/userId`) | engagement | |
| Cosmos DB | `estateai/ai-requests` (pk `/feature`, TTL 30 d) | ai | tokens, cost, latency, status, feedback |
| Redis | db 0 | gateway (rate limits), identity (OTP, magic links), search (NL cache), all (revocation, `feature_flags` hash — written by ai admin API) | keys prefixed per owner: `rl:`, `otp:`, `magic:`, `nl:`, `jwt:`, `feature_flags` |

Rule: a service never reads another service's store. It calls an `/internal/*` endpoint or consumes events.

## 4. Event catalogue (Azure Service Bus)

Envelope: `estate_common.events.Event` → `{id, type, source, subject, time, data}` (CloudEvents-style).
Delivery is at-least-once; every handler is idempotent.

| Topic | Event type | Producer | Subscriptions (consumer) | `data` | Consumer action |
|---|---|---|---|---|---|
| `listing-events` | `listing.published` | listing | `search` | listing snapshot (no PII) | upsert read model + embed |
| `listing-events` | `listing.updated` | listing | `search` | listing snapshot | upsert + re-embed |
| `listing-events` | `listing.unpublished` | listing | `search` | listing snapshot | delete from read model |
| `listing-events` | `listing.document_uploaded` | listing | `ai` | `document_id, listing_id, storage_key, filename, kind` | extract → chunk → embed → store |
| `listing-events` | `listing.document_deleted` | listing | `ai` | `document_id, listing_id` | delete that document's chunks |
| `ai-events` | `ai.document_processed` | ai | `listing` | `document_id, listing_id, status, error` | update document status |
| `engagement-events` | `engagement.enquiry_created` | engagement | `notification` | `enquiry_id, agent_id, listing_id` (ids only) | fetch details, email agent |
| `identity-events` | `identity.user_suspended` | identity | `listing` | `user_id` | live listings → `suspended` (hidden) |
| `identity-events` | `identity.user_reinstated` | identity | `listing` | `user_id` | `suspended` listings → `published` |
| `identity-events` | `identity.user_deleted` | identity | `listing`, `engagement`, `ai` | `user_id` | listing: archive all; engagement: delete favourites/saved searches, scrub sent enquiries, delete received ones; ai: unlink AI logs |

Topology is declared in `infra/local/servicebus/Config.json` (emulator) and must be mirrored in
Azure IaC (task T4.12). Adding a consumer = new subscription; producers don't change.

## 5. Key request flows

**NL search** — `web → gateway → search`: search calls `ai /internal/nl-parse` (Gemini Flash-Lite,
structured output) **in parallel** with `ai /internal/embeddings`, then runs hybrid ranking on its own
read model. If parsing fails/times out (2 s) → fallback mode (vector or full-text only).

**Listing Q&A** — `web → gateway → ai` (SSE): ai fetches the fact sheet from `listing /internal/.../facts`,
retrieves chunks from its own pgvector store (scoped to the listing), streams Gemini's answer,
validates citations, logs to Cosmos.

**Publish listing** — `listing` commits, then publishes `listing.published` → `search` indexes it
(eventual consistency, typically < 2 s locally).

**Upload document** — `listing` stores PDF in Blob, status `processing`, publishes
`listing.document_uploaded` → `ai` ingests → `ai.document_processed` → `listing` sets `ready`/`failed`.

**Enquiry** — `engagement` stores in Cosmos, publishes ids → `notification` fetches details and emails the agent.

## 6. Local environment (docker compose)

```bash
cp .env.example .env
docker compose up -d --build          # first run pulls emulators; Service Bus needs ~30–60 s to be ready
curl -X POST localhost:8002/internal/dev/seed?count=60   # sample listings → events → search index
open http://localhost:3000
```

| URL | What |
|---|---|
| http://localhost:3000 | Web app (nginx build) — or `cd web && npm run dev` → http://localhost:5173 |
| http://localhost:8080/health/deep | Gateway + all service health |
| http://localhost:800{1..5}/docs | Per-service OpenAPI (local only) |
| http://localhost:8025 | Mailpit — sign-in codes, enquiry emails |
| http://localhost:1234 | Cosmos DB Data Explorer |
| http://localhost:18888 | Aspire Dashboard — traces and structured logs |
| localhost:10000 | Azurite Blob (use Azure Storage Explorer) |

Dev accounts (seeded when `APP_ENV=local`): `agent@example.com` (verified agent), `admin@example.com`.
In local mode the OTP is also returned in the API response and shown on the login page.

**Emulator limits (the emulator refuses to start otherwise):** Service Bus message TTL ≤ 1 hour and duplicate-detection
window ≤ 5 minutes (`infra/local/servicebus/Config.json`). Azure allows far longer; set production values in IaC (T4.12).
The emulator also needs SQL Server to finish recovery first, so it takes 30–60 s to accept connections; services retry until then.

**End-to-end check:** `python scripts/smoke_test.py` drives 29 checks through the gateway (auth, search, events, documents, AI, enquiries, logout).

**Resources:** the full stack needs roughly 6–8 GB RAM for Docker (SQL Server for the Service Bus
emulator and the Cosmos emulator are the heaviest). Service Bus emulator images are x64.

## 7. Azure production mapping

| Concern | Local | Azure |
|---|---|---|
| Compute | docker compose | **Azure Container Apps** (one app per service; `notification` as a worker app with KEDA Service Bus scaler) |
| Public entry | gateway container | Azure Front Door → gateway (or API Management) |
| Frontend | nginx container | **Azure Static Web Apps** |
| PostgreSQL | pgvector container | Azure Database for PostgreSQL Flexible Server (pgvector extension allow-listed) |
| Cosmos DB | emulator | Azure Cosmos DB for NoSQL (serverless for MVP) |
| Messaging | Service Bus emulator | Azure Service Bus Standard (topics) |
| Blob | Azurite | Azure Storage account (private) + CDN for images |
| Redis | redis:7 | Azure Managed Redis |
| Email | Mailpit | Azure Communication Services Email |
| Identity | identity service OTP | Microsoft Entra External ID (ADR-0009) |
| Secrets | `.env` | Azure Key Vault + Container Apps secret references; managed identities for Storage/Service Bus/Cosmos |
| Telemetry | Aspire Dashboard | Application Insights via Azure Monitor OpenTelemetry |
| LLM + embeddings | Gemini API (`GEMINI_API_KEY`, or `AI_FAKE=true` offline) | Gemini API with the key in Key Vault and egress allowed to `generativelanguage.googleapis.com`; or Vertex AI (`genai.Client(vertexai=True, …)` — only `app/llm/gemini_client.py` changes) (ADR-0013) |
| IaC | compose + Config.json | Bicep / `azd` (task T4.12) |

## 8. Production patterns (where each lives)

| Pattern | Gateway (YARP) | Python services (`libs/common`) | ADR |
|---|---|---|---|
| Authentication | JWT RS256 via identity JWKS, revocation check, bad tokens rejected at the edge | `estate_common.auth` verifies again (defence in depth) | 0015 |
| Authorization | Route policies `authenticated` / `agent` / `admin` | `Agent` / `Admin` / `User` dependencies + ownership checks | 0015 |
| Rate limiting | Redis sliding window per user or IP; in-memory global per-IP limiter | — | 0014 |
| Caching | Redis output cache for anonymous GETs (30 s – 6 h) | `TwoLevelCache` (in-process L1 + Redis L2, pub/sub invalidation): listing detail, classic search (versioned), AI fact sheets | 0014, 0016 |
| Retries | GET/HEAD only, 2× jittered backoff (Polly) | `ResilientClient`: idempotent calls only | 0014, 0016 |
| Circuit breaker | Per upstream service (Polly) | Per dependency (`ResilientClient`) | 0014, 0016 |
| Timeouts | Per route (`default` 30 s, `ai-stream` 90 s, `upload` 120 s) | Per client and per call; AI calls per feature | 0014, 0016 |
| Health checks | Active (`/health/ready` every 10 s) + passive (transport failures); `/health/deep` | `/health` liveness, `/health/ready` checks Postgres / Redis / Cosmos | 0016 |
| Global exception handling | `IExceptionHandler` + forwarder-error middleware → error envelope | `install_error_handling` → error envelope | — |
| Idempotency | — | `IdempotencyMiddleware` on create listing, enquiries, saved searches | 0016 |
| Reliable events | — | Transactional outbox (listing, ai); outbox-in-document (engagement); Service Bus duplicate detection; idempotent consumers | 0016 |
| Schema migrations | — | Alembic per Postgres service, run before start | 0016 |
| Observability | JSON logs, request id, OpenTelemetry | structlog JSON, request id, OpenTelemetry | — |

## 9. Cross-cutting conventions

- **Auth:** the gateway validates JWTs at the edge, and every service verifies them again (`estate_common.auth`); services never trust identity headers.
- **Internal endpoints:** `/internal/*` are reachable only inside the network (gateway returns 404; Container Apps internal ingress).
- **Errors:** one envelope everywhere (`estate_common.errors`), `X-Request-Id` propagated by the gateway.
- **Resilience:** consumers retry connection forever with backoff; AI calls have timeouts + fallbacks; Cosmos init retries on startup.
- **Versioning:** REST under `/api/v1`; event `type` names are stable — breaking payload changes get a new type (`listing.published.v2`).
- **Schema changes:** Alembic per Postgres-backed service (`services/<svc>/migrations`); `alembic upgrade head` runs before the server starts.
