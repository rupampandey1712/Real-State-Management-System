# 0012 — Cosmos DB for engagement data and AI request logs
- Status: Accepted
- Date: 2026-09-27
- Deciders: Tech lead
- Related: ADR-0002 (Postgres for relational + vectors), docs/architecture.md §3

## Context
Two data sets are document-shaped, write-heavy, and always accessed by a single key:
- Engagement: enquiries (by agent), favourites and saved searches (by user).
- AI request logs: one document per LLM call, append-mostly, retention-limited (30 days), queried by feature/time.

## Decision
Use **Azure Cosmos DB for NoSQL** (emulator locally) for these, with partition keys matching the
access pattern: `enquiries` → `/agentId`; `favourites`, `saved-searches` → `/userId`;
`ai-requests` → `/feature` with container-level **TTL** for retention. Relational listing data and
vectors stay in PostgreSQL (ADR-0002).

## Consequences
- ➕ Serverless/autoscale throughput, native TTL for retention (NFR-10), no schema migrations for logs.
- ➕ Demonstrates polyglot persistence per service ownership.
- ➖ Cross-partition queries (e.g. admin "all negative feedback") are costlier — use the change feed to
  project into an analytics store if the admin dashboard needs heavy aggregation (T4.4).
- ➖ `/feature` has low cardinality; fine at MVP volume. Revisit with a synthetic key (`feature#yyyy-mm-dd`) above ~10k RU/s.

## Alternatives considered
- **PostgreSQL tables** (original design) — simpler, but retention jobs and write volume compete with OLTP.
- **Table Storage** — cheaper but limited querying.
