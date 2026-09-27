# Architecture Decision Records (ADRs)

Short records of significant, hard-to-reverse decisions. One file per decision: `NNNN-short-title.md`.

**Rules**
- Write an ADR when a choice affects structure, data, dependencies, security, or cost, or when
  someone will later ask "why did we do it this way?".
- Never rewrite an accepted ADR's decision — create a new ADR that supersedes it and update both statuses.
- Keep them short (≤ 1 page). Link from `design.md` where relevant.
- Use `/new-adr <title>` in Claude Code to scaffold one.

| # | Title | Status | Date |
|---|---|---|---|
| [0001](0001-monorepo-nextjs-fastapi.md) | Monorepo with Next.js + FastAPI | Superseded by 0008/0009 | 2026-09-27 |
| [0002](0002-postgres-pgvector.md) | PostgreSQL + pgvector instead of a separate vector DB | Accepted | 2026-09-27 |
| [0003](0003-embedding-provider.md) | Embedding provider | Accepted (see 0013) | 2026-09-27 |
| [0004](0004-llm-gateway.md) | Single LLM gateway (pattern) — provider superseded by 0013 | Accepted | 2026-09-27 |
| [0005](0005-auth-authjs-jwt.md) | Auth.js on web, JWT verification in API | Superseded by 0009 | 2026-09-27 |
| [0006](0006-sse-streaming.md) | Server-Sent Events for Q&A streaming | Accepted | 2026-09-27 |
| [0007](0007-background-jobs-arq.md) | Background jobs with arq on Redis | Superseded by 0011 | 2026-09-27 |
| [0008](0008-microservices-on-azure.md) | Microservices on Azure Container Apps | Accepted | 2026-09-27 |
| [0009](0009-react-spa-and-auth.md) | React SPA (Vite); auth via identity service / Entra External ID | Accepted | 2026-09-27 |
| [0010](0010-azure-emulators-local-dev.md) | Azure emulators for local development | Accepted | 2026-09-27 |
| [0011](0011-service-bus-events.md) | Integration events on Azure Service Bus topics | Accepted | 2026-09-27 |
| [0012](0012-cosmos-db-engagement-and-ai-logs.md) | Cosmos DB for engagement data and AI request logs | Accepted | 2026-09-27 |
| [0013](0013-gemini-llm-provider.md) | Google Gemini as the LLM and embedding provider | Accepted | 2026-09-27 |
| [0014](0014-yarp-api-gateway.md) | YARP (.NET 10) as the API gateway | Accepted | 2026-09-27 |
| [0015](0015-token-lifecycle.md) | Token lifecycle: RS256 + JWKS, rotating refresh tokens, revocation | Accepted | 2026-09-27 |
| [0016](0016-outbox-and-resilience.md) | Transactional outbox, idempotency and resilience patterns | Accepted | 2026-09-27 |

## Template
```markdown
# NNNN — Title
- Status: Proposed | Accepted | Superseded by NNNN | Deprecated
- Date: YYYY-MM-DD
- Deciders: <roles>
- Related: FR-x, design §y, ADR-zzzz

## Context
What problem are we solving? What forces/constraints apply (scale, team, cost, time, compliance)?

## Decision
What we chose, stated plainly.

## Consequences
Positive, negative, and follow-up work. What becomes easier/harder?

## Alternatives considered
- Option A — why not.
- Option B — why not.

## Revisit when
Concrete trigger for re-evaluating (e.g. "> 10M vectors", "p95 > X").
```
