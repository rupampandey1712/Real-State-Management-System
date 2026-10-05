# CLAUDE.md — Instructions for AI Coding Agents

This file is loaded automatically by Claude Code (and is readable by any AI coding agent).
It is the **entry point** for AI-assisted work on this repository. Details live in `docs/`.

---

## 1. Project in one line
**EstateAI** — an India-first real-estate platform built as **microservices on Azure** (runnable
locally on Azure emulators) with a **React** SPA and GenAI features: natural-language search,
AI listing descriptions, and a grounded listing Q&A assistant powered by Google Gemini.

## 2. Source of truth (read in this order)
| # | File | Read when |
|---|---|---|
| 1 | `docs/architecture.md` | Always: which service owns what, events, ports, emulators |
| 1a | `docs/backend-guide.md` | Before writing Python service code: patterns, recipes, pitfalls |
| 1b | `docs/integrations.md` · `docs/api-tracing.md` · `docs/api-reference.md` | When touching an integration or debugging a flow |
| 1c | `docs/azure-deployment.md` | Before changing config, secrets, infrastructure or anything deploy-related |
| 2 | `docs/requirements.md` | For the feature you touch (FR-x / NFR-x IDs) |
| 3 | `docs/design.md` | For the section (§) your task references: data model, API contracts, AI pipelines |
| 4 | `docs/tasks.md` | To pick / confirm your task and its "Done when" |
| 5 | `docs/plan.md` | To understand phase goals and what is *not* in scope yet |
| 6 | `docs/decisions/` | Before changing architecture, libraries, data stores or service boundaries |
| 7 | `docs/ai/*.md` | Before touching `services/ai/` or `evals/` |
| 8 | `docs/security.md` | Before touching auth, uploads, rate limits, logging or PII |
| 9 | `docs/glossary.md` | When a domain term is unclear (BHK, lakh, RERA, carpet area…) |

**If code and docs disagree, stop and flag it — don't guess.** If a change alters a design
decision, update the doc in the same change (and add an ADR if it's architectural).

## 3. Workflow for every task (spec-driven)
1. **Locate** the task in `docs/tasks.md`; read its FR/NFR and design § references.
2. **Plan**: list the services and files you'll touch, events/contracts affected, tests to add, doc updates.
3. **Implement** in small steps with tests alongside.
4. **Verify**: run the checks in §5 for every service you touched. AI changes → run the eval suite.
5. **Close**: mark the task `[x]`, update docs/ADRs, summarise what changed and what's left.

Slash commands in `.claude/commands/`: `/next-task`, `/new-adr`, `/new-prompt-version`, `/spec-check`.

## 4. Architecture at a glance
```
web (React/Vite) → gateway (YARP) :8080 → identity :8001 | listing :8002 | search :8003 | ai :8004 | engagement :8005
events (Azure Service Bus): listing-events → search, ai · ai-events → listing · engagement-events → notification
```
| Layer | Choice | Ref |
|---|---|---|
| Frontend | React 19 + TypeScript (strict) + Vite, React Router, TanStack Query, Tailwind v4 | ADR-0009 |
| Services | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async; shared `libs/common/estate_common` | ADR-0008 |
| Data | Postgres + pgvector (identity, listing, search, ai DBs) · Cosmos DB (engagement, AI logs) · Blob · Redis | ADR-0002, 0012 |
| Messaging | Azure Service Bus topics/subscriptions, CloudEvents-style envelope | ADR-0011 |
| LLM + embeddings | Google Gemini via official `google-genai` SDK (`GEMINI_API_KEY`) — **only in `services/ai`** | ADR-0004, 0013 |
| Local | docker compose + Azurite, Cosmos emulator, Service Bus emulator, Mailpit, Aspire Dashboard | ADR-0010 |
| Azure | Container Apps, Static Web Apps, PostgreSQL Flexible, Cosmos, Service Bus, Key Vault, App Insights | architecture.md §7 |

## 5. Commands
```bash
# Full stack (from repo root; first time: cp .env.example .env)
docker compose up -d --build
docker compose logs -f <service>
curl -X POST "localhost:8002/internal/dev/seed?count=60"      # sample listings
# UIs: web :3000 · Mailpit :8025 · Cosmos explorer :1234 · Aspire traces :18888 · gateway /health/deep

# One Python service (tests run without Docker)
cd services/<svc>
pip install -r ../../libs/common/requirements.txt -r ../../libs/common/requirements-dev.txt -r requirements.txt
pytest -q                     # pytest.ini adds ../../libs/common to the path
ruff check . && mypy app

# Gateway (YARP)
cd services/gateway && dotnet test

# Migrations (Postgres services; from services/<svc>, PYTHONPATH=../../libs/common;.)
alembic revision --autogenerate -m "<change>" && alembic upgrade head

# Web
cd web && npm install && npm run dev        # :5173, proxies /api → gateway :8080
npm run typecheck && npm run build

# CI (.github/workflows/ci.yml) runs all of the checks below on every push and pull request

# End-to-end against the running stack (31 checks through the gateway)
python scripts/smoke_test.py

# Frontend ↔ backend ↔ gateway contract (run after any API or UI change; exits 1 if out of sync)
python scripts/check_api_sync.py

# AI evals (hits the running ai service; with AI_FAKE=false this costs money)
python evals/run_evals.py --suite search
```

## 6. Repository layout
```
libs/common/estate_common/   settings, logging, errors, auth (JWT/JWKS), events, messaging, outbox, http (resilience),
                             cache (two-level), idempotency, migrations, telemetry, db
services/
  gateway/        YARP (.NET 10, C#): routes + policies in src/Gateway/appsettings.json; tests in tests/Gateway.Tests
  identity/       OTP sign-in, JWT, roles                         (Postgres identity, Redis)
  listing/        listings, images, documents, fact sheet, seed   (Postgres listing, Blob) → listing-events
  search/         read-model projection, classic + NL hybrid search (Postgres search + pgvector, Redis)
  ai/             LLM gateway, prompts, guardrails, describe, Q&A, ingestion (Postgres ai + pgvector, Cosmos)
    app/llm/          base.py (protocol) · gemini_client.py · fake.py
    app/prompts/      <id>.v<N>.md + loader.py
    app/features/     nl_search.py · rules.py · describe.py · qa.py · schemas.py
  engagement/     enquiries, favourites, saved searches            (Cosmos) → engagement-events
  notification/   worker: engagement-events → email (Mailpit / ACS)
  <svc>/app/main.py · config.py · tests/ · Dockerfile · requirements.txt · pytest.ini · alembic.ini + migrations/ (Postgres services)
web/src/         pages/ · components/ · lib/ (api.ts, sse.ts, auth.tsx, types.ts)
infra/local/     postgres/init.sql · servicebus/Config.json
evals/           run_evals.py · search/cases.jsonl
docs/            specs — the project's memory
```

## 7. Conventions

### Microservice boundaries (most important)
- A service **never** reads another service's database or container. Use its `/internal/*` API or its events.
- New cross-service interaction → update `docs/architecture.md` §4 (events) or §2 (HTTP) in the same change.
- New event type or topic → add it to `estate_common/events.py`, `infra/local/servicebus/Config.json`, and architecture.md §4.
- Event handlers must be **idempotent** and events must carry **no PII** (ids + non-personal data only).
- `/internal/*` routes must never be added to the gateway routes (`services/gateway/src/Gateway/appsettings.json`).
- **Full-stack slices only:** a new public endpoint ships with the UI that uses it (or a reason in
  `BACKEND_ONLY` in `scripts/check_api_sync.py`), and a new UI call ships with its endpoint and gateway route.
  `python scripts/check_api_sync.py` must say IN SYNC before a task is done; then regenerate `docs/api-reference.md`
  with `python scripts/gen_api_reference.py`.
- New public route → add it to the gateway config with the right `AuthorizationPolicy`, `RateLimiterPolicy`,
  `OutputCachePolicy` (anonymous GETs only) and `TimeoutPolicy`; add a gateway test.

### Production patterns (ADR-0014, 0015, 0016) — use them, don't re-invent them
- Publishing an event from a Postgres service → `estate_common.outbox.add_event(session, ...)` **before** commit. Never publish directly after commit.
- Calling another service → `estate_common.http.ResilientClient` (timeouts, retries for idempotent calls, circuit breaker). Never a bare `httpx` client.
- Caching reads → `estate_common.cache.TwoLevelCache`; invalidate on the write or on the event that changes the data.
- New unsafe POST that users could double-submit → add its path to the service's `IdempotencyMiddleware`.
- New dependency → add a readiness check to `create_app(..., readiness={...})`.
- Shared code goes in `libs/common` only if it is cross-cutting (no domain logic).

### Python
- Type hints everywhere; settings via the service's `config.py` (never `os.environ` in feature code).
- Errors: raise `estate_common.errors.*` (NotFound, Forbidden, ValidationFailed, AIUnavailable…); never return raw exception text.
- Auth: use the `Agent`, `Admin`, `User`, `OptionalUser` dependencies from `estate_common.auth`; check ownership in the handler/service.
  Only the identity service signs tokens (RS256); everything else verifies via JWKS. Never add a shared JWT secret.
- Money: integer paise (`price_minor`) + currency. **Never floats.** APIs accept rupees (`price_inr`) and return `{amount_minor, currency, display}`.
- Logging: structlog; never log secrets, tokens, or raw PII.

### TypeScript (web)
- `strict`; no `any`. API calls only through `lib/api.ts` / `lib/sse.ts`. Server state via TanStack Query; search state in the URL.
- Accessible by default: labels for inputs, `aria-live` for streaming text, keyboard-usable controls.

### GenAI (critical)
- **Never** import `google.genai` outside `services/ai/app/llm/gemini_client.py` and `services/ai/app/embeddings.py`. Features call `get_llm()` / `get_embedder()`.
- Prompts live in `services/ai/app/prompts/<id>.v<N>.md`; never inline prompts in Python. Untrusted values use `| untrusted`.
- Machine-read output: JSON mode with `response_json_schema` built from a Pydantic model, then Pydantic validation (see `gemini_client.parse`). Keep output models flat. Don't set `temperature`; tune depth with `thinking_level` in prompt front-matter.
- Model IDs only from config (`AI_MODEL_*`). Current defaults: `gemini-3.1-flash-lite` (search), `gemini-3.8-flash` (describe, Q&A), `gemini-3.1-pro-preview` (offline judge), `gemini-embedding-001` (768 dims).
- Every AI feature has a timeout, a non-AI fallback, a feature flag, deterministic guardrails, and an eval suite.
- Tests use `AI_FAKE=true` (FakeLLMClient) — unit tests never call the real API.

### Data
- Postgres schema changes → Alembic migration in the owning service. Never `create_all`.
- Cosmos: choose the partition key from the dominant query; document it in the service's `store.py` docstring.

### Git
- Branch `feat/T3b.4-short-name`; Conventional Commits with task id; PR lists task, services touched, tests, eval summary (AI), screenshots (UI), docs updated.

## 8. Do NOT
- Don't invent listing facts in AI output (see `docs/ai/guardrails.md`).
- Don't send buyer PII to any LLM or embedding provider, or put it on the event bus.
- Don't use the well-known emulator keys against real Azure, or commit a real `.env`.
- Don't add a dependency without saying why; architectural ones need an ADR.
- Don't disable tests, lint rules or type checks to make CI pass.
- Don't implement later-phase features "while you're there" — add them to the Parking lot in tasks.md.
- Don't run real-model evals without stating the expected cost first.

## 9. When stuck
State what you tried, what you observed, and the decision you need. Propose a recommended option.
Don't silently change requirements or service boundaries to make implementation easier.
