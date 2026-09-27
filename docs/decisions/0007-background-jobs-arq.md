# 0007 — Background jobs with arq on Redis
- Status: Superseded by 0011
- Date: 2026-09-27
- Deciders: Tech lead
- Related: design §5

## Context
Image resizing, PDF parsing, chunking, embedding, re-embedding backfills and retention cleanup
must run outside the request cycle, with retries. The API is async Python; Redis is already required.

## Decision
- Use **arq** (asyncio job queue on Redis) with a separate `worker` process/container sharing the API codebase.
- Jobs are idempotent and keyed by entity ID; retries with exponential backoff; cron jobs via arq's cron support.
- Job status that users care about (document processing) is persisted in Postgres, not only Redis.

## Consequences
- ➕ Native async (same SQLAlchemy async session + httpx clients as the API); small and simple.
- ➕ No new infrastructure beyond Redis.
- ➖ Smaller ecosystem/monitoring than Celery; add a simple admin view of queue depth + failures.
- ➖ Redis persistence must be configured (AOF) to avoid losing queued jobs on restart.

## Alternatives considered
- **Celery** — mature but sync-first, heavier configuration.
- **Dramatiq / RQ** — sync-first.
- **Managed queues (SQS + Lambda)** — more infra and cold starts for PDF work; reconsider at larger scale.

## Revisit when
Job volume > 50k/day, need for complex workflows, or multi-language workers.
