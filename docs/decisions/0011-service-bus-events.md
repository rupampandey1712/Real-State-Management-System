# 0011 — Integration events on Azure Service Bus topics
- Status: Accepted
- Date: 2026-09-27
- Deciders: Tech lead
- Related: supersedes ADR-0007 (arq); docs/architecture.md §4; libs/common/estate_common/messaging.py

## Context
With microservices, state changes must propagate between services (listing → search index,
document upload → AI ingestion → listing status, enquiry → email) without synchronous coupling.

## Decision
- **Azure Service Bus topics** with one **subscription per consuming service** (pub/sub). Topics:
  `listing-events`, `ai-events`, `engagement-events` (catalogue in docs/architecture.md §4).
- Events are CloudEvents-shaped JSON (`estate_common.events.Event`: id, type, source, subject, time, data).
- **At-least-once delivery:** consumers are idempotent (upserts keyed by aggregate id; chunk
  re-ingestion deletes then inserts). Failures abandon the message → retry → dead-letter after
  `MaxDeliveryCount`.
- Events carry **no PII** — consumers fetch details via internal HTTP when needed (e.g. notification).
- Background work that used to be "jobs" is now event consumers inside the owning service
  (search indexing, AI ingestion). Scheduled jobs (retention purges) will use Container Apps jobs (T4.7).

## Consequences
- ➕ Loose coupling; consumers can be added without touching producers.
- ➕ Same code against the emulator and Azure (connection string only).
- ➖ Publish-after-commit can lose an event if the process dies between commit and publish.
  **Follow-up T1.14: transactional outbox** in listing and engagement services.
- ➖ Eventual consistency must be visible in UX (e.g. "Processing…" document status).

## Alternatives considered
- **Event Grid** — great for Azure resource events; weaker for app-level competing consumers + DLQ.
- **Storage Queues** — cheaper, but no topics/subscriptions or sessions.
- **Dapr pub/sub** — portable abstraction; could be layered on later in Container Apps.
