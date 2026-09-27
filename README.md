# EstateAI

A real-estate platform (India-first) with GenAI features, built as **microservices on Azure** and
fully runnable on your machine with **Azure emulators**:

- 🔎 **Natural-language search** — "2BHK under 80 lakh near a metro in Pune, quiet area"
- ✍️ **AI listing descriptions** — grounded, fair-housing-safe drafts for agents
- 💬 **Listing Q&A** — instant answers with citations from the listing and its PDFs

## Quick start (local, no Azure account needed)

Prerequisites: Docker Desktop (≈ 8 GB RAM allocated, x64), Node 20+ (optional, for web dev mode).

```bash
cp .env.example .env
docker compose up -d --build                         # emulators + 7 services + web
curl localhost:8080/health/deep                      # wait until all services are "ok"
curl -X POST "localhost:8002/internal/dev/seed?count=60"   # sample listings → indexed via Service Bus
```

Open **http://localhost:3000** and sign in as `agent@example.com`. Locally, the one-time code is
shown on the login page and also appears in Mailpit.

| URL | What |
|---|---|
| http://localhost:3000 | Web app (React) |
| http://localhost:8080 | API gateway (`/health/deep`) |
| http://localhost:8001…8005/docs | Per-service OpenAPI |
| http://localhost:8025 | Mailpit (emails) |
| http://localhost:1234 | Cosmos DB Data Explorer |
| http://localhost:18888 | Aspire Dashboard (traces, logs) |

AI runs **offline by default** (`AI_FAKE=true`, `EMBEDDING_PROVIDER=fake`). To use **Google Gemini**, set
`AI_FAKE=false`, `EMBEDDING_PROVIDER=gemini` and `GEMINI_API_KEY` (from Google AI Studio) in `.env`, then
`docker compose up -d ai search`.

For frontend hot reload: `cd web && npm install && npm run dev` → http://localhost:5173.

## Architecture

```
React SPA → gateway → identity · listing · search · ai · engagement      (HTTP + JWT)
                      listing ⇒ Service Bus ⇒ search, ai ⇒ listing        (events)
                      engagement ⇒ Service Bus ⇒ notification → email
                      ai → Gemini (3.1 Flash-Lite · 3.8 Flash · embedding-001)
```

| Azure service | Local emulator |
|---|---|
| Blob Storage | Azurite |
| Cosmos DB | Cosmos DB Linux emulator |
| Service Bus | Service Bus emulator |
| PostgreSQL Flexible Server | Postgres + pgvector |
| Managed Redis | Redis |
| Communication Services Email | Mailpit |
| Application Insights | Aspire Dashboard (OTLP) |

Full details: [docs/architecture.md](docs/architecture.md).

## Documentation (spec-driven development)
| File | Purpose |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Rules for AI coding agents: conventions, commands, service boundaries |
| [docs/getting-started.md](docs/getting-started.md) | **Start here:** run the app locally, URLs, accounts, troubleshooting |
| [docs/architecture.md](docs/architecture.md) | Services, data ownership, events, emulators, Azure mapping |
| [docs/integrations.md](docs/integrations.md) | Every integration top to bottom: protocol, config, code, failure behaviour, Azure mapping |
| [docs/backend-guide.md](docs/backend-guide.md) | FastAPI services: structure, auth, errors, data, events, resilience, caching, testing, recipes |
| [docs/api-tracing.md](docs/api-tracing.md) | Trace any API from browser to database and back (request ids, traces, state) |
| [docs/api-reference.md](docs/api-reference.md) | Every endpoint (generated from code by `scripts/gen_api_reference.py`) |
| [docs/azure-deployment.md](docs/azure-deployment.md) | Deploying to Azure: resources, required code changes, CLI walkthrough, CI/CD, costs |
| [docs/requirements.md](docs/requirements.md) | What and why: personas, user stories, NFRs, compliance |
| [docs/design.md](docs/design.md) | How: data model, API contracts, GenAI pipelines, security, testing |
| [docs/plan.md](docs/plan.md) | When: phases, milestones, Definition of Done |
| [docs/tasks.md](docs/tasks.md) | Task checklist, with the current status |
| [docs/decisions/](docs/decisions/) | ADRs 0001–0012 |
| [docs/ai/](docs/ai/) | Prompts, evals, guardrails |
| [docs/security.md](docs/security.md) · [docs/runbook.md](docs/runbook.md) · [docs/glossary.md](docs/glossary.md) | Security, operations, terms |

## Working with Claude Code
1. Open the repo in Claude Code (it loads `CLAUDE.md`).
2. Run `/next-task`. The first open task is **T0.10: the first full-stack run**.
3. Review the plan before it codes and the diff after.
4. Use `/new-adr`, `/new-prompt-version` and `/spec-check` as needed.

## Tests
```bash
python scripts/smoke_test.py                 # end to end against the running stack: 29 checks
python scripts/check_api_sync.py             # frontend ↔ gateway ↔ backend contract
```
```bash
cd services/gateway && dotnet test          # YARP gateway integration tests
cd libs/common && pytest -q                  # resilience, cache, idempotency, auth
```
```bash
cd services/ai && pip install -r ../../libs/common/requirements.txt -r ../../libs/common/requirements-dev.txt -r requirements.txt && pytest -q
cd services/listing && pip install -r requirements.txt && pytest -q
cd web && npm run build
```
