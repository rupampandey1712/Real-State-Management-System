# Tasks — EstateAI

> Working task list for humans and AI agents. Pick the **first unchecked task whose dependencies are
> done** in the current phase, unless assigned otherwise. Mark `[x]` in the same change that completes it.
>
> Format: `ID · Title` — **Refs** · **Deps** · **Est** · **Done when**
> Legend: `[ ]` todo · `[~]` in progress / partial · `[x]` done · 🤖 touches the GenAI layer
> Estimates: S ≤ 2h · M ≤ 1 day · L ≤ 2 days
>
> **Scaffold status (2026-09-27):** the microservices scaffold is in the repo. Unit tests pass
> (listing 16, ai 16), every service imports cleanly, the web app type-checks and builds, and
> `docker compose config` validates. **The full stack has not yet been run end-to-end in Docker** —
> that is T0.10 and should be done first.

---

## Phase 0 — Foundation

- [x] **T0.1 · Monorepo scaffold** — `services/*`, `libs/common`, `web/`, `infra/local`, `evals/`, docs.
- [x] **T0.2 · Docker Compose with Azure emulators** — Azurite, Cosmos vNext, Service Bus (+ SQL Server), pgvector Postgres, Redis, Mailpit, Aspire Dashboard (ADR-0010).
- [x] **T0.3 · Shared library** — settings, JSON logging, error envelope + request id, JWT auth, events, Service Bus helpers, OTel, DB helpers.
- [x] **T0.4 · Service skeletons** — gateway, identity, listing, search, ai, engagement, notification with Dockerfiles and `/health`.
- [x] **T0.5 · React SPA skeleton** — Vite, TS strict, Tailwind v4, React Router, TanStack Query, API client, SSE client.
- [x] **T0.9 · `.env.example`** — all settings documented, emulator credentials.
- [x] **T0.10 · First full-stack run** — done 2026-09-27: all 16 containers up, migrations applied to live Postgres, `scripts/smoke_test.py` 29/29 through the gateway. Bugs found and fixed: gateway image copied Windows `obj/` (dockerignore patterns), Service Bus emulator limits (TTL ≤ 1 h, duplicate window ≤ 5 min), dev accounts on `.local` rejected by email validation (now `@example.com`), Azure SDK header logging noise.
  - Done when: `docker compose up -d --build` → all containers healthy; `/health/deep` all `ok`; seed 60 listings; they appear in search; OTP login works; enquiry email shows in Mailpit; traces in Aspire. Fix whatever breaks and note emulator quirks in architecture.md §6.
- [ ] **T0.6 · Tooling** — Refs: CLAUDE.md §7 · Deps: T0.10 · Est: S
  - Done when: ruff + mypy config at repo root, eslint for web, pre-commit hooks; all pass.
- [ ] **T0.7 · OpenAPI → TS types** — Refs: ADR-0009 · Deps: T0.10 · Est: M
  - Done when: script pulls each service's `/openapi.json`, generates `web/src/lib/api-types.ts` (openapi-typescript); `lib/types.ts` replaced; CI fails on drift.
- [x] **T0.8 · CI pipeline** — `.github/workflows/ci.yml`: lint, Python tests (matrix), migrations up/down/up on real Postgres + pgvector, gateway tests, web build, API contract + generated-reference check, Docker image builds, end-to-end (compose + smoke test). Deploy workflow: see azure-deployment.md §5 (needs Azure first).
  - Done when: GitHub Actions matrix over `services/*` (ruff, mypy, pytest), web (typecheck, build, vitest), image builds, compose smoke test (`/health/deep`).
- [ ] **T0.11 · Integration test harness** — Deps: T0.10 · Est: M
  - Done when: pytest fixtures spin up Postgres/Redis (testcontainers) per service; one API test per service (happy path + auth failure).

## Phase 1 — Core listings & classic search

- [x] **T1.1 · Identity: OTP sign-in, JWT, roles, dev seed users** — FR-6.1, ADR-0009.
- [x] **T1.2 · Listing schema** — models for listings, images, documents (create_all bootstrap).
- [x] **T1.3 · Money & units** — paise storage, lakh/crore parse/format, 16 unit tests.
- [x] **T1.4 · Listing CRUD + status transitions + events** — create/patch/publish/unpublish, ownership checks, `listing.*` events.
- [x] **T1.5 · Image upload** — EXIF strip, WebP 1600/400 to Blob, `/api/v1/media/*`.
- [x] **T1.6 · Agent listing editor UI** — form, amenities, uploads, publish (single page; multi-step wizard later).
- [x] **T1.7 · Search projection + classic search API** — consumer builds read model; filters, sort, cursor.
- [x] **T1.8 · Search page** — URL-driven, NL + classic modes, "Show more".
- [x] **T1.9 · Listing detail page** — gallery, facts, amenities, Q&A, enquiry.
- [x] **T1.10 · Enquiries** — engagement service (Cosmos), agent enquiries list, notification email.
- [~] **T1.11 · Seed data** — 60 synthetic listings via `/internal/dev/seed` (no images). Todo: sample photos + sample PDFs for Q&A.
- [x] **T1.12 · Map view** — FR-2.3 · done 2026-10-04 (ADR-0018): MapLibre + OpenFreeMap tiles, lazy-loaded; list/map toggle on the search page with focusable price pins and "Search this area" (`bbox` on `GET /search` and `POST /search/nl`, `ix_search_geo`); pin on the listing page; click/drag pin picker in the editor.
  - Done when: MapLibre + OSM tiles on search page; markers from `lat/lng`; "search this area" (bbox filter added to search API).
- [x] **T1.17 · Requirements gap pass (FR-1, FR-2)** — done 2026-10-04: archive + duplicate (FR-1.1, 1.5); HEIC, photo reorder/delete (FR-1.2); balconies, open parking, property age, possession date, map pin in the editor; publish blocked with per-field errors (FR-1 AC); RERA required for under-construction sale listings (FR-1.4, §7); fair-housing check on agent text at publish; classic filter panel + sort incl. relevance (FR-2.1, 2.2); editable AI chips (FR-3.2).
- [x] **T1.13 · Alembic per Postgres service** — initial revisions for identity, listing, search, ai (generated from models, compiled to SQL offline); run before start in compose. Todo: verify against a live DB in T0.10.
  - Done when: identity, listing, search, ai have Alembic envs and an initial migration; `create_all` only when `APP_ENV=local`; migrations run as a compose one-shot and a Container Apps job.
- [x] **T1.14 · Transactional outbox** — listing + ai (Postgres outbox + relay), engagement (outbox-in-document + relay), Service Bus duplicate detection (ADR-0016). Todo: crash test in T0.10.
  - Done when: listing and engagement write events to an outbox in the same transaction; a relay publishes and marks sent; tested by killing the publisher mid-way.
- [ ] **T1.15 · Search perf check** — FR-2 AC, NFR-8 · Deps: T0.10 · Est: S
  - Done when: 100k synthetic listings; k6 p95 < 300 ms for classic search; results in `docs/perf/phase1.md`.
- [x] **T1.16 · Agent verification flow** — Q4 in requirements · done 2026-10-04: buyers apply from `/account` (name, phone, agency, RERA agent no.) → unverified agent; admins filter "awaiting verification" and verify. Manual KYC for the MVP; Q4 still open for the process itself.

## Phase 2 — GenAI foundation

- [x] **T2.2 · LLM gateway** 🤖 — `LLMClient` protocol; Gemini client (`google-genai`: JSON-schema output + Pydantic validation, streaming, `thinking_level`, safety blocks, retries, timeouts); Fake client. Mock-SDK tests (8).
- [x] **T2.3 · AI request logging & pricing** 🤖 — Cosmos `ai-requests` with TTL, tokens, cost, latency, status, feedback.
- [x] **T2.5 · Embedding providers** 🤖 — hashing (offline) + `gemini-embedding-001` (768 dims, normalised); `/internal/embeddings`.
- [x] **T2.6 · Prompt loader** 🤖 — versioned files, front-matter, StrictUndefined, `untrusted` filter.
- [x] **T2.7 · Guardrails** 🤖 — sanitize, PII redaction, advice screen, fair-housing, number check, citations; unit tests.
- [~] **T2.9 · Eval harness** 🤖 — `evals/run_evals.py --suite search` done (12 cases). Todo: describe + qa suites, LLM judge (`judge_grounding`), baselines, CI workflow.
- [ ] **T2.1 · ADR-0003 embedding decision** 🤖 — Deps: T0.10, T1.11 · Est: M
  - Done when: 2–3 providers compared on 50 query→listing pairs (Recall@10, nDCG@10, cost); ADR accepted.
- [x] **T2.10 · Re-index command** — `POST listing /internal/dev/republish` re-emits `listing.updated` through the outbox.
  - Done when: listing `/internal/dev/republish` (or CLI) re-emits `listing.updated` for all published listings; search rebuilds.
- [ ] **T2.11 · First real-Gemini smoke test** 🤖 — Deps: T0.10 · Est: S
  - Done when: `AI_FAKE=false`, `EMBEDDING_PROVIDER=gemini` + `GEMINI_API_KEY`: NL search, describe and Q&A work end-to-end; the JSON schemas are accepted by the API (incl. nullable enums); Cosmos shows token, thinking and cached-token counts.

## Phase 3a — Description generator (FR-4)
- [x] **T3a.7 · Improve my text** 🤖 — FR-4.4 · done 2026-10-04: prompt `improve.v1`, `POST /ai/improve` (agent, flag `ai_improve`, number + fair-housing post-checks, one regeneration), editor panel. Todo: eval cases (with T3a.1).
- [x] **T3a.2 · Fact sheet builder** — `listing /internal/listings/{id}/facts` (S1..Sn, no contact/address).
- [x] **T3a.3 · Prompt `describe.v1` + feature** 🤖 — structured output, post-checks, one regeneration, warnings.
- [x] **T3a.4 · `POST /api/v1/ai/describe`** — agent-only, owner check, flag, gateway rate limit.
- [x] **T3a.5 · Editor AI panel** — tone/length/notes, warnings, editable draft, explicit accept.
- [ ] **T3a.1 · Describe eval set** 🤖 — 50 cases incl. 10 adversarial agent notes · Est: M
- [ ] **T3a.6 · Describe eval gate** 🤖 — Deps: T3a.1, T2.9 · Est: S — gate passes; baseline committed; flag on in staging.

## Phase 3b — NL search (FR-3)
- [x] **T3b.2 · `SearchFilters` + prompt `nl_search.v1`** 🤖
- [x] **T3b.3 · Post-processing** — city/locality normalisation, range swaps, protected-preference removal.
- [x] **T3b.4 · Hybrid ranking** — filters + cosine + filter fit + freshness, config weights, match reasons.
- [x] **T3b.5 · `POST /api/v1/search/nl` + cache + fallback** 🤖
- [x] **T3b.6 · NL search UI** — NL box, removable chips (→ classic), assumptions, non-property hint.
- [ ] **T3b.1 · Search eval set to 150 cases** 🤖 — current 12 · Est: M
- [~] **T3b.7 · Eval gate + weight tuning + `near` POIs** 🤖 — Deps: T3b.1 · Est: L — `near` ranking done 2026-10-04 (bundled OSM-derived POI list, weight 0.10, ADR-0018). Todo: eval gate and weight tuning with real Gemini.

## Phase 3c — Documents + Q&A (FR-1.3, FR-5)
- [x] **T3c.1 · Document upload** — PDF magic bytes, size/count limits, Blob, `listing.document_uploaded`.
- [x] **T3c.2 · Ingestion consumer** 🤖 — pypdf, chunking with page ranges, embeddings, status event back.
- [x] **T3c.4 · Retrieval scoped to listing** — pgvector query `WHERE listing_id = :id`.
- [x] **T3c.5 · Prompt `qa.v1` + feature** 🤖 — advice screen, streaming, citation validation, answer status.
- [x] **T3c.6 · SSE endpoint + suggestions + feedback** — disconnect stops the stream.
- [x] **T3c.7 · Q&A panel UI** — streaming, citations, suggestions, 👍/👎, "Ask the agent" prefill.
- [ ] **T3c.3 · Q&A eval + red-team sets** 🤖 — 20 listings with PDFs, 100 cases, 30 red-team · Est: M
- [x] **T3c.8 · Agent documents list UI + owner-only document download** — status list with live polling; owner-only download and delete (`listing.document_deleted` → ai drops chunks).
- [ ] **T3c.9 · Q&A eval gate** 🤖 — Deps: T3c.3, T2.9 · Est: S
- [ ] **T3c.10 · Isolation test** — integration test proving Q&A never retrieves another listing's chunks · Est: S
- [ ] **T3c.11 · Chaos test** — NFR-2 · Est: S — stop the ai container: search falls back, listing pages and editor still work.

## Phase 4 — Hardening, Azure & launch
- [x] **T4.1 · Rate limiting** — YARP gateway, Redis sliding window per user/IP, in-memory global per-IP limiter, named policies fail closed (ADR-0014).
- [x] **T4.16 · YARP gateway** — .NET 10, per-route policies, edge JWT + revocation, output cache, Polly retries + circuit breaker, health checks, error envelope; 8 integration tests.
- [x] **T4.17 · Token lifecycle** — RS256 + JWKS + key rotation, rotating refresh tokens with reuse detection, logout / logout-all, Redis revocation, in-memory SPA token (ADR-0015); 7 identity tests + 5 auth tests.
- [x] **T4.18 · Service resilience** — `ResilientClient` (retries + circuit breaker), `TwoLevelCache`, `IdempotencyMiddleware`, readiness checks in every service (ADR-0016); 16 library tests.
- [x] **T4.2 · AI feedback endpoint** 🤖
- [x] **T4.6 · Favourites & saved searches** — API (engagement) + UI: Save on cards and listing page, Save this search, `/me/saved` page.
- [x] **T4.19 · People admin + account page** — `GET /admin/users`, `/admin` page (roles, agent verification, key rotation), `/account` page (sign out of all devices).
- [x] **T4.20 · API sync check** — `scripts/check_api_sync.py`: backend ↔ gateway ↔ frontend; wire into CI with T0.8.
- [x] **T4.21 · Sign-in methods** — FR-6.1 · done 2026-10-04 (ADR-0017): email magic link (fragment token, single use) sent with the code; Google ID-token sign-in when `GOOGLE_CLIENT_ID` is set. Todo: real Google client id per environment.
- [x] **T4.22 · Q&A and privacy details** — FR-5.2, FR-5.6, §7 · done 2026-10-04: clickable citations show the field value or document passage and jump to the fact; optional comment on 👍/👎; "AI answers can be incomplete — verify with the agent." in the panel; `/privacy` notice; consent checkbox on enquiries.
- [x] **T4.3 · Admin moderation** — FR-7.1 · done 2026-10-04: listing takedown/restore and account suspend/reinstate, reason required and logged (`moderation_actions`, `admin_actions`); suspension hides the agent's live listings via `identity.user_suspended`; Admin → Listings / People tabs with history.
- [x] **T4.4 · Admin AI dashboard** 🤖 — FR-7.2/7.3 · done 2026-10-04: per feature per day requests, tokens, cost, p50/p95 latency, error rate, 👍/👎 (aggregated in Python over the 30-day log; switch to the change feed if volume grows); 👎 review and JSONL export as eval candidates. Todo: 👍/👎 comment is optional in the Q&A panel; describe/improve have no rating UI yet.
- [x] **T4.5 · Runtime feature flags** — FR-7.4 · done 2026-10-04 (ADR-0019): Redis hash, config defaults, 5 s cache; Admin → AI toggles; `GET /ai/features` hides disabled UI.
- [~] **T4.7 · Account deletion & retention jobs** — FR-6.4, NFR-10 · done 2026-10-04: `DELETE /me` scrubs at once and emits `identity.user_deleted` (listing archives, engagement erases favourites/saved searches/enquiry contact details, ai unlinks logs); purge after 30 days; enquiries deleted after 2 years; enquiry consent recorded. Todo: the purge and retention loops run inside identity/engagement — move them to Container Apps jobs with T4.12.
- [ ] **T4.8 · Security review** — docs/security.md · Est: L
- [ ] **T4.9 · Load & a11y tests** — NFR-6/8/9 · Est: M
- [ ] **T4.10 · Alerts, runbook drill, backup restore drill** · Est: M
- [ ] **T4.11 · SEO for listing pages** — ADR-0009 · Est: M — pre-render or edge SSR for `/listings/:id`.
- [ ] **T4.12 · Azure IaC** — architecture.md §7 · Est: L — Bicep/`azd`: Container Apps env + apps, Postgres Flexible (pgvector), Cosmos, Service Bus topics/subscriptions (mirror Config.json), Storage, Redis, Key Vault, managed identities, App Insights, Static Web Apps.
- [ ] **T4.13 · Configurable guardrail terms & templates** — docs/ai/guardrails.md §4–5 · Est: S
- [ ] **T4.14 · Signing keys in Key Vault / Entra External ID** — ADR-0015 · Est: L — move private keys out of Postgres (Key Vault) or switch to Entra; verifiers already use JWKS.
- [ ] **T4.15 · Outbox cleanup job** — ADR-0016 · Est: S — delete outbox rows published more than 7 days ago (Container Apps job).

---

## Parking lot (ideas raised during work — not scheduled)
- _Format: `- idea — raised in T#.# — why`._
