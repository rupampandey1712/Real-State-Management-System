# 0016 — Transactional outbox, idempotency and resilience patterns
- Status: Accepted
- Date: 2026-09-27
- Deciders: Tech lead
- Related: ADR-0011 (events), ADR-0014 (gateway resilience); libs/common/estate_common/{outbox,http,cache,idempotency}.py

## Context
Services published events *after* committing, so a crash in between lost the event and left read
models (search) or document statuses stuck. Service-to-service HTTP had no retries or circuit breaking,
POSTs could be duplicated by double-clicks or retries, and every read hit the database.

## Decision
1. **Transactional outbox (Postgres services: listing, ai).** Events are inserted into an `outbox` table
   in the same transaction as the state change (`add_event`). `OutboxRelay` publishes pending rows in
   batches (`FOR UPDATE SKIP LOCKED`, so replicas can relay concurrently) and marks them sent, backing off
   when Service Bus is down. The event id is the Service Bus message id and topics have **duplicate
   detection** (10-minute window), so relay retries don't produce duplicates.
2. **Outbox-in-document (Cosmos: engagement).** Each enquiry carries `eventPublished`; the request
   publishes immediately and a relay republishes anything still unsent after 30 s with a stable event id.
3. **Idempotent consumers.** Upserts keyed by aggregate id (search), delete-then-insert of chunks (ai),
   status overwrite (listing). At-least-once delivery is safe.
4. **Resilient HTTP (`ResilientClient`).** Timeouts, retries with jittered exponential backoff for
   idempotent calls only, and a per-dependency circuit breaker (5 consecutive failures → open 30 s →
   half-open trial). Failures surface as `DependencyUnavailable` (503 envelope with `Retry-After`).
5. **Idempotency keys.** `IdempotencyMiddleware` on unsafe POSTs (create listing, enquiries, saved
   searches): same key + same body replays the stored response; same key + different body → 422;
   concurrent duplicate → 409. The SPA sends one key per form instance.
6. **Two-level cache (`TwoLevelCache`).** L1 in-process TTL cache + L2 Redis, single-flight loading,
   invalidation broadcast over Redis pub/sub. Used for listing detail (invalidated on write), classic
   search (versioned; any listing event bumps the version) and AI fact sheets (invalidated by listing events).
   Redis failures degrade to "no cache", never to errors.
7. **Health.** `/health` (liveness) and `/health/ready` (Postgres, Redis, Cosmos checks) in every
   service; the gateway's active health checks use `/health/ready`.
8. **Schema migrations.** Alembic per Postgres service; `alembic upgrade head` runs before the server in
   compose and as a Container Apps job in Azure. No more `create_all` at startup.

## Consequences
- ➕ No lost events; duplicates are filtered at the broker and tolerated by consumers.
- ➕ A slow or dead dependency fails fast instead of exhausting connections.
- ➕ Hot reads served from memory or Redis.
- ➖ Eventual consistency windows: outbox relay (≤ ~1 s normally), engagement relay (≤ 60 s after a publish failure), edge cache (≤ 30 s).
- ➖ Outbox rows accumulate — a cleanup job for rows published more than 7 days ago is task T4.15.
