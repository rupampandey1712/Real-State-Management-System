# 0002 — PostgreSQL + pgvector instead of a separate vector DB
- Status: Accepted
- Date: 2026-09-27
- Deciders: Tech lead
- Related: FR-3, FR-5, design §2, §4.3, §4.5

## Context
- NL search needs **hybrid** queries: hard filters (price, city, BHK, geo radius) combined with
  vector similarity and full-text search, in one ranked result set.
- Q&A retrieval is always scoped to a single listing (small candidate set per query).
- MVP scale: ≤ 100k listings, ≤ 1M document chunks, ~50 RPS search.
- We already need Postgres (relational data, PostGIS for geo).

## Decision
- Store embeddings in PostgreSQL using `pgvector` (`vector(1024)`, cosine distance, HNSW indexes)
  alongside relational data. Use `postgis` for geo and built-in `tsvector` for full-text.
- Store `embedding_model` next to each vector so stale vectors can be detected and re-embedded.

## Consequences
- ➕ One datastore: transactional consistency, no sync pipeline, filters + vectors + FTS + geo in one SQL query.
- ➕ Simple local dev and ops (one managed Postgres).
- ➖ HNSW + selective filters can reduce recall; mitigated by over-fetching (`LIMIT 200` candidates) then re-ranking, and by setting `hnsw.ef_search` appropriately.
- ➖ Heavy vector workloads compete with OLTP on the same instance; add a read replica for search if needed.

## Alternatives considered
- **Pinecone / Weaviate / Qdrant** — strong vector features, but extra infra, cost, and dual-write consistency for ~100k items.
- **Elasticsearch/OpenSearch** — good hybrid search, but heavy to operate for an MVP.

## Revisit when
> 10M vectors, search p95 > 300 ms after tuning, or vector queries measurably affecting OLTP latency.
