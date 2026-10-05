# Search performance — Phase 1 (T1.15)

> Run 2026-10-04 · FR-2 AC (p95 < 300 ms server-side at 100k listings), NFR-8 (API p95 < 300 ms non-AI),
> NFR-9 (50 RPS search on a single DB node).

## Setup
- Data: 100,218 published listings in the search read model (`perf/seed_search.py --count 100000`), spread over
  the 3 launch cities and 16 localities. Embeddings NULL (classic search doesn't read them).
- Load: `perf/k6/search.js`, constant 50 requests/s for 60 s, against the search service directly (server-side,
  no gateway rate limits). Mix: 55 % filter searches (city, type, BHK, budget, sometimes locality/amenity,
  all four sort orders), 20 % map-area (`bbox`), 15 % `near` + relevance, 10 % page 2.
- **Every request is unique** (random budget, jittered map box), so no cache layer answers — this is the
  worst case. Real traffic repeats queries and hits the two-level cache and the gateway output cache.
- Environment: docker compose on a developer laptop (Windows, Docker Desktop), search service = **one** uvicorn
  worker in `--reload` mode, Postgres 16 container with default settings. Production runs without reload and
  scales replicas on concurrency (infra/azure/modules/apps.bicep), so these numbers are pessimistic.

## Results

| Run | filters p95 | map p95 | near p95 | page 2 p95 | errors | verdict |
|---|---|---|---|---|---|---|
| Cache hits allowed (repeating filter combos) | 45 ms | 16 ms | 9 ms | 14 ms | 0 % | ✅ |
| Every request uncached — before fix | 346 ms | 389 ms | 323 ms | 351 ms | 0 % | ❌ |
| Every request uncached — after fix | **205 ms** | **164 ms** | **191 ms** | **150 ms** | 0 % | ✅ |

Database time per query (`EXPLAIN ANALYZE`): 10 ms (filters, `ix_search_filters` + top-N sort), 20 ms (map box,
`ix_search_geo`), 17 ms (200 relevance candidates). Medians at 50 RPS were ~30 ms.

## What was fixed
The service was CPU-bound, not database-bound: requests queued behind each other in one worker. Every query
loaded whole ORM rows, including the description and the 768-dim `embedding` (parsed from text for up to 200
rows per relevance query). Queries now load only the columns a result card and the scorer need
(`ranking.RESULT_COLUMNS`). On real data, where every row has an embedding, the saving is larger than measured here.

## Not measured here
- **NL search** end-to-end (FR-3 AC p95 < 2.5 s) needs the real Gemini model, which costs money — run with T2.11.
- **Listing page LCP < 2.5 s on 4G** (NFR-8): Lighthouse in CI against staging (see `web/e2e`, T4.9).
- 1M document chunks (NFR-9) for Q&A retrieval: needs the ingestion pipeline at scale; follow-up.

## Re-run
```bash
python perf/seed_search.py --count 100000
docker run --rm -i -e BASE_URL=http://host.docker.internal:8003 grafana/k6 run - < perf/k6/search.js
python perf/seed_search.py --clean
```
