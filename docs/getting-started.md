# Getting started — run EstateAI locally

> Everything runs on your machine with Docker and Azure emulators. No Azure subscription or AI key is
> needed: the AI runs in offline mode by default. Verified end to end on 2026-09-27 (`scripts/smoke_test.py`, 29/29).
> Related: [architecture.md](architecture.md) · [api-tracing.md](api-tracing.md) · [integrations.md](integrations.md)

---

## 1. Prerequisites

| Tool | Version | Why |
|---|---|---|
| Docker Desktop | 4.x with Compose v2 | Runs every service and emulator |
| Memory for Docker | **8 GB** (Settings → Resources) | SQL Server (for the Service Bus emulator) ≈ 1 GB, Cosmos emulator ≈ 0.6 GB, the rest ≈ 150 MB each |
| CPU architecture | x86-64 | The Service Bus emulator image is x64 only |
| Python | 3.12+ | Only for running tests and scripts outside Docker |
| Node.js | 20+ | Only for frontend hot reload (`npm run dev`) |
| .NET SDK | 10.0 | Only for building/testing the gateway outside Docker |

## 2. Start the stack

```bash
cp .env.example .env                 # local defaults; emulator keys are public and safe to use locally
docker compose up -d --build         # first run downloads ~5 GB of images and builds 8 images
```

What happens, in order:
1. **Backing services start:** Postgres (4 databases created by `infra/local/postgres/init.sql`), Redis, Azurite,
   Cosmos DB emulator, SQL Server, Mailpit, Aspire Dashboard.
2. **Service Bus emulator** waits for SQL Server to finish recovery, then creates the topics and subscriptions
   from `infra/local/servicebus/Config.json`. This takes **30–60 s**; services retry their connections meanwhile
   (you'll see `consumer_connection_failed_retrying` warnings until it's up — that's expected).
3. **Python services** run `alembic upgrade head` (identity, listing, search, ai), then start uvicorn with hot reload.
4. **Gateway** (YARP) starts and probes every service's `/health/ready` every 10 s.
5. **Web** is served by nginx on port 3000.

### Check it's healthy

```bash
docker compose ps                                  # all 16 containers "running"
curl http://localhost:8080/health/deep             # every cluster "Healthy" (can take ~30 s after start)
```

### Load sample data

```bash
curl -X POST "http://localhost:8002/internal/dev/seed?count=60"
```
Creates 60 listings owned by the dev agent. Each one goes through the outbox → Service Bus → search index,
so they appear in search within a few seconds.

### Run the end-to-end test

```bash
pip install httpx
python scripts/smoke_test.py        # 29 checks through the gateway; exits 1 on the first failure
```

## 3. Use the app

Open **http://localhost:3000**.

| Account | How to sign in | Can do |
|---|---|---|
| `agent@example.com` | Email → the 6-digit code is shown on the login page locally (also in Mailpit) | Create/publish listings, AI descriptions, PDF uploads, see enquiries |
| `admin@example.com` | Same | Everything + People page (roles, agent verification, key rotation) |
| Any other email | Same — created on first sign-in as a home seeker | Search, save homes and searches, ask listings, send enquiries |

## 4. Local URLs

| URL | What |
|---|---|
| http://localhost:3000 | Web app (nginx build) |
| http://localhost:5173 | Web app with hot reload (`cd web && npm install && npm run dev`) |
| http://localhost:8080 | API gateway — `/health`, `/health/ready`, `/health/deep` |
| http://localhost:8001/docs … 8005/docs | Swagger UI per service (identity, listing, search, ai, engagement) |
| http://localhost:8025 | Mailpit — sign-in codes and enquiry emails |
| http://localhost:18888 | Aspire Dashboard — distributed traces, structured logs, metrics |
| http://localhost:1234 | Cosmos DB Data Explorer |
| localhost:5432 | Postgres (`estate` / `estate`; databases `identity`, `listing`, `search`, `ai`) |
| localhost:6379 | Redis |
| localhost:10000 | Azurite Blob (Azure Storage Explorer: "Local storage emulator") |
| localhost:5672 | Service Bus emulator (AMQP) |

## 5. Everyday commands

```bash
docker compose logs -f listing search            # follow logs (JSON, one line per request/event)
docker compose restart ai                        # restart one service
docker compose up -d --build gateway             # rebuild after C# changes (Python services hot-reload)
docker compose exec postgres psql -U estate -d listing      # SQL shell into a service's database
docker compose exec redis redis-cli                          # inspect cache, rate-limit and revocation keys
docker compose down                               # stop (data kept in volumes)
docker compose down -v                            # stop and wipe all data
```

**Hot reload:** each Python service mounts `services/<svc>/app` and `libs/common`; editing a `.py` file restarts
that service in about a second. The gateway and web images must be rebuilt after changes (or use `npm run dev`).

## 6. Turn on real AI (Google Gemini)

Edit `.env`:
```
AI_FAKE=false
EMBEDDING_PROVIDER=gemini
GEMINI_API_KEY=<key from https://aistudio.google.com/apikey — use a paid-tier key>
```
Then:
```bash
docker compose up -d ai search                        # reload settings
curl -X POST http://localhost:8002/internal/dev/republish   # re-embed all listings with Gemini embeddings
```
Real calls cost money. Every call is logged with tokens and cost in Cosmos (`estateai/ai-requests`).

## 7. Tests without Docker

```bash
# Python (per service; pytest.ini puts libs/common on the path)
pip install -r libs/common/requirements.txt -r libs/common/requirements-dev.txt
cd libs/common && pytest -q                                   # 21 tests
cd services/<svc> && pip install -r requirements.txt && pytest -q

# Gateway
cd services/gateway && dotnet test                            # 10 integration tests

# Web
cd web && npm install && npm run build                        # type-check + production build

# Contract between frontend, gateway and backend
python scripts/check_api_sync.py
```

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `servicebus` exits right after start | Config.json value above an emulator limit (TTL > 1 h, duplicate window > 5 min) | Check `docker compose logs servicebus` for "Expected time to be less than…" |
| Services log `consumer_connection_failed_retrying` | Service Bus emulator not ready yet | Wait 30–60 s after start |
| `/health/deep` shows a cluster `Unhealthy` | That service is still starting, or its `/health/ready` fails | `curl localhost:800X/health/ready` shows which dependency failed |
| Gateway image fails with "Unable to find fallback package folder" | Local `bin/`/`obj/` copied into the image | Ensure `services/gateway/.dockerignore` has `**/bin/` and `**/obj/` |
| Sign-in returns 422 for your email | Reserved domains such as `.local` or `.test` are rejected by email validation | Use a normal domain (e.g. `@example.com`) |
| Image pulls fail with "no such host" | Docker Desktop DNS not ready right after start | Retry `docker compose up -d` |
| 429 on sign-in | Gateway auth rate limit (10/min per IP) | Wait a minute |
