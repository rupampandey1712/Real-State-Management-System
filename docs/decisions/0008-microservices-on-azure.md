# 0008 — Microservices on Azure Container Apps
- Status: Accepted — the gateway implementation is superseded by 0014 (YARP)
- Date: 2026-09-27
- Deciders: Tech lead, product owner
- Related: supersedes the backend half of ADR-0001; docs/architecture.md; ADR-0010, 0011, 0012

## Context
The product owner asked for a microservices architecture targeting Azure, with the whole stack
runnable locally on Azure emulators. Forces:
- AI features have very different scaling, cost and release profiles from CRUD (LLM latency, token
  budgets, prompt releases) — they benefit from independent deployment and scaling.
- Search read traffic is much higher than listing writes.
- Team is small, so every extra service must earn its operational cost.

## Decision
Seven deployable units, each owning its data, communicating by HTTP (queries) and Azure Service Bus
events (state changes). Target runtime: **Azure Container Apps** (one app per service, internal
ingress; only the gateway is public).

| Service | Owns | Store |
|---|---|---|
| gateway | routing, CORS, rate limits | Redis |
| identity | users, roles, OTP | PostgreSQL `identity` + Redis |
| listing | listings, images, documents | PostgreSQL `listing` + Blob Storage |
| search | search read model, ranking | PostgreSQL `search` (pgvector) + Redis cache |
| ai | LLM gateway, prompts, embeddings, RAG chunks, AI telemetry | PostgreSQL `ai` (pgvector) + Cosmos DB |
| engagement | enquiries, favourites, saved searches | Cosmos DB |
| notification | outbound email (worker, no HTTP) | — |

Rules: no shared databases; no service reads another's tables; shared code only in `libs/common`
(cross-cutting, no domain logic); `/internal/*` endpoints are never exposed by the gateway.

## Consequences
- ➕ AI service can scale, deploy and roll back independently; LLM keys live in one service only.
- ➕ Search can be scaled/replicated for read load without touching listing writes.
- ➕ Clear ownership boundaries map well onto AI coding agents working per-service.
- ➖ Eventual consistency: a newly published listing appears in search after the event is processed (seconds).
- ➖ More moving parts locally (mitigated by one `docker compose up`) and in CI.
- ➖ Cross-service changes need contract discipline (event catalogue in docs/architecture.md §4).

## Alternatives considered
- **Modular monolith (ADR-0001)** — simpler; would still be a good choice for a very small team. Rejected per product direction and the AI-service isolation benefit.
- **AKS (Kubernetes)** — more control, much more ops. Container Apps gives scale-to-zero, revisions, Dapr and KEDA without cluster management.
- **Azure Functions per endpoint** — cold starts and fragmented code for SSE-heavy Q&A.

## Revisit when
Team > 10 engineers (split further) or ops burden outweighs benefits (merge search into listing first).
