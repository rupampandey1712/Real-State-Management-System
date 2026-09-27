# Implementation Plan — EstateAI

> Status: Draft v0.3 (microservices + Azure emulators) · Last updated: 2026-09-27
> Progress: the Phase 0 scaffold and first cuts of most Phase 1–3 features are implemented — see the status note in [tasks.md](tasks.md).
> Roadmap and sequencing. Checkbox-level work lives in [tasks.md](tasks.md).

---

## 1. Guiding approach
1. **Walking skeleton first** — web → api → db → CI working end-to-end before any feature.
2. **Non-AI baseline before AI** — classic search ships first: it's the fallback *and* the benchmark.
3. **Evals before exposure** — every AI feature has a golden dataset and a passing gate before its flag is turned on.
4. **Vertical slices** — each task delivers DB → API → UI → tests for one capability, not layer-by-layer.
5. **Docs are code** — requirements/design/tasks are updated in the same PR as the change.
6. **AI-agent friendly** — tasks are small (≤ 1 day, ideally ≤ 400 lines diff), with explicit "Done when".

## 2. Team & roles (assumed)
| Role | Responsibility |
|---|---|
| Tech lead | Architecture, ADRs, reviews, eval gates |
| Full-stack engineer(s) | Feature slices |
| AI coding agent (Claude Code) | Implements tasks from `tasks.md` under review |
| Product owner | Requirements, acceptance, eval dataset labelling |
| Designer (part-time) | Search, listing page, chat UI |

## 3. Timeline overview
```
Week:        1     2     3     4     5     6     7     8
Phase 0   [████]
Phase 1         [██████████]
Phase 2                     [████]
Phase 3a                          [████]
Phase 3b                          [████████]
Phase 3c                                [██████████]
Phase 4                                             [████]
Eval data  ...........[collect & label continuously]......
```

---

## Phase 0 — Foundation (Week 1)
**Goal:** An empty-but-working monorepo with CI, where any engineer or agent can run everything in one command.

**Deliverables**
- Monorepo layout per `CLAUDE.md` §6 (`services/*`, `libs/common`, `web/`, `infra/local`)
- Docker Compose with Azure emulators: Azurite, Cosmos DB, Service Bus, plus pgvector Postgres, Redis, Mailpit, Aspire Dashboard (ADR-0010)
- Seven FastAPI/worker microservices + `libs/common` (config, logging, error envelope, auth, events, messaging) (ADR-0008)
- Database-per-service bootstrap (Alembic per service follows in T1.13)
- React + Vite SPA: Tailwind, React Router, TanStack Query, API + SSE clients (ADR-0009)
- Tooling: ruff, mypy, pytest, eslint, tsc, vitest, pre-commit; OpenAPI → TS type generation
- CI pipeline; `.env.example`; `.claude/commands/` workflows

**Exit criteria**
- `docker compose up` → web at :3000 shows "API: healthy".
- CI green on a trivial PR in < 8 minutes.
- New contributor setup time < 15 minutes following README.

---

## Phase 1 — Core listings & classic search (Weeks 2–3)
**Goal:** A usable, non-AI listings site — the product must be valuable without AI.

**Deliverables**
- Auth (magic link + Google), roles, agent verification flag (FR-6.1)
- Listings schema, CRUD, status transitions, validation (FR-1.1, FR-1.4)
- Image upload pipeline with worker resize (FR-1.2)
- Agent multi-step listing editor (without AI step)
- Classic search API (filters, sort, cursor pagination, bbox) + search page + map (FR-2)
- Listing detail page (SSR, SEO metadata, structured data `schema.org/RealEstateListing`)
- Enquiry form → agent dashboard (FR-6.3)
- Seed script: ~500 synthetic listings across Pune/Bengaluru/Mumbai; POI import (metro, schools)
- Locality gazetteer per city (canonical names + aliases)

**Exit criteria**
- J2 (without AI) completes in the UI; buyer finds the listing via filters and map.
- p95 classic search < 300 ms on 100k synthetic listings (k6 smoke).
- Start of eval data collection: 50 real-style NL queries written by product.

---

## Phase 2 — GenAI foundation (Week 4)
**Goal:** Shared, tested AI infrastructure. No user-facing AI yet.

**Deliverables**
- ADR-0003 accepted (embedding provider) after mini retrieval eval
- `LLMClient` gateway (Gemini + Fake), pricing table, AI request logging (ADR-0004, ADR-0013)
- `embeddings` provider + search projection consumer (embeds on `listing.published`) + re-index command
- Prompt loader with versioning + config-selected active version
- Guardrails module: sanitize, PII redaction, untrusted wrapping, number fact-check, fair-housing check
- `evals/` harness: dataset loader, runner, scorers, markdown report, CI workflow (manual trigger)
- Feature flag service (env default + Redis override)

**Exit criteria**
- All seed listings embedded; vector similarity query works in psql.
- A scripted call through the gateway logs a row in `ai_requests` with tokens + cost.
- Guardrail unit tests ≥ 95% branch coverage.
- `run_evals.py --suite smoke` runs end-to-end.

---

## Phase 3 — AI features (Weeks 5–7)
Each sub-phase ships **behind its feature flag** and is enabled in staging only after its eval gate passes.

### 3a — Listing description generator (Week 5) — FR-4
- Eval set (50 listings with fact sheets, 10 adversarial agent notes)
- Prompt `describe.v1`, structured output `DescribeOutput`, post-checks, regenerate-once logic
- Endpoint + editor step UI (tone/length, warnings, accept)
- **Gate:** 0 unsupported facts, 0 fair-housing violations, p95 < 8 s

### 3b — NL search (Weeks 5–6) — FR-3
- Eval set (150 queries: easy/medium/hard, rent vs sale, lakh/crore/k, localities, non-property queries)
- `SearchFilters` schema, prompt `nl_search.v1`, post-processing (gazetteer, money)
- Hybrid ranking SQL + POI `near` scoring; ranking-weight tuning against eval set
- Cache, fallback, endpoint; UI: NL box, chips, assumptions, fallback notice
- **Gate:** ≥ 90% field accuracy, ≥ 95% correct `is_property_query`, p95 < 2.5 s; relevance nDCG@10 ≥ classic baseline + 10%

### 3c — Documents + Listing Q&A (Weeks 6–7) — FR-1.3, FR-5
- Document upload + `process_document` job (extract, chunk, embed)
- Eval set (100 Q&A across 20 listings incl. 25 unanswerable) + red-team set (30)
- Prompt `qa.v1`, retrieval, SSE streaming, citation validation, refusal templates
- Q&A panel UI with citations, suggestions, feedback, "Ask the agent"
- **Gate:** ≥ 95% grounded, ≥ 95% correct unknown, 0 red-team failures, first-token p95 < 2 s

**Phase 3 exit criteria**
- All three flags on in staging; evals green and reports committed as baselines.
- Chaos test: block Gemini API egress → search, listing pages, and editor still work.

---

## Phase 4 — Hardening & launch (Week 8)
**Deliverables**
- Rate limiting on all public AI + enquiry endpoints
- Admin: moderation, AI metrics dashboard, negative-feedback review/export, runtime flags (FR-7)
- Favourites & saved searches (FR-6.2); account deletion (FR-6.4)
- Security review against `docs/security.md` checklist; ZAP baseline; red-team rerun
- Load test (k6) at target RPS; accessibility audit (axe + keyboard)
- Production infra, alerts, runbook ([runbook.md](runbook.md)), backups tested (restore drill)
- Launch checklist (below)

**Launch checklist**
- [ ] All Must-have FRs accepted by product
- [ ] NFR measurements recorded (latency, cost/request, a11y)
- [ ] Eval baselines committed; nightly eval job running
- [ ] Alerts firing to on-call channel (test alert sent)
- [ ] Backup restore tested
- [ ] Privacy policy & AI disclaimer live
- [ ] Rollback plan rehearsed (flags off + previous image)

---

## Phase 5 — Post-MVP backlog (prioritise after launch data)
| Item | Value | Effort | Notes |
|---|---|---|---|
| Hindi / Hinglish NL search | High | M | Add eval cases; model handles it, gazetteer needs aliases |
| Photo understanding: auto-caption & amenity tagging | High | M | Vision input to Gemini; feeds description + search |
| Saved-search alerts with AI summaries | Med | M | Daily digest email |
| Automated valuation estimate (AVM) | High | L | Needs transaction data; regulated messaging |
| Agent insights: "what buyers ask about your listing" | Med | S | Cluster Q&A questions |
| Compare listings with AI | Med | S | Grounded side-by-side |
| Conversational search refinement ("cheaper", "closer to metro") | Med | M | Multi-turn filter editing |

---

## 4. Milestones
| ID | Target | Deliverable | Demo |
|---|---|---|---|
| M0 | End W1 | Skeleton + CI | `docker compose up` |
| M1 | End W3 | Classic listings site | Agent lists, buyer finds |
| M2 | End W4 | AI platform layer | Gateway logs, embeddings, eval harness |
| M3 | End W7 | AI features in staging | J1 + J2 with AI |
| M4 | End W8 | Production launch | Live |

## 5. Definition of Done (every task)
- Code + tests merged; CI green; no lint/type suppressions added
- Acceptance criteria of linked FR met (or explicitly partial with follow-up task)
- Docs updated (design/ADR/tasks); OpenAPI types regenerated if API changed
- For AI changes: eval run summary in PR, no gate regression
- For UI: mobile + desktop screenshots, keyboard accessible

## 6. Environments & release
- Trunk-based: short-lived branches → PR → `main` → auto-deploy staging → manual promote to prod.
- AI features released by flag, not by deploy. Rollback = flip flag or revert prompt version in config.

## 7. Dependencies & risks to the plan
| Dependency / risk | Impact | Mitigation |
|---|---|---|
| Gemini API key (paid tier) + budget approval | Blocks real-AI testing | Request in Week 1 |
| Embedding provider decision | Blocks Phase 2 | Mini-eval in Week 3 |
| Eval data labelling by product | Blocks Phase 3 gates | Start in Week 2, 30 min/day |
| POI / map data licensing | Affects `near` scoring | Use OSM (ODbL) with attribution |
| Scope creep into Phase 5 items | Delays launch | Park in backlog, PO decides |
