# Design — EstateAI

> Status: Draft v0.3 (microservices) · Last updated: 2026-09-27
> Implements: [requirements.md](requirements.md) · Decisions: [decisions/](decisions/) · AI details: [ai/](ai/)

**Contents**
1. Architecture overview (→ [architecture.md](architecture.md)) · 2. Data model · 3. API design · 4. GenAI layer · 5. Background jobs ·
6. Frontend · 7. Security · 8. Observability · 9. Configuration · 10. Deployment ·
11. Testing · 12. Failure modes · 13. Capacity & cost · 14. Risks

---

## 1. Architecture overview

EstateAI runs as **microservices on Azure** (ADR-0008) with a **React SPA** (ADR-0009), fully runnable
locally on **Azure emulators** (ADR-0010). The service catalogue, data ownership, event catalogue,
local ports and Azure mapping live in **[architecture.md](architecture.md)** — read it first.
This document covers feature-level design: data model, API contracts, GenAI pipelines, security,
testing and failure modes.

```
React SPA -> gateway -> identity | listing | search | ai | engagement       (HTTP, JWT)
             listing ==(Service Bus)==> search, ai ==(Service Bus)==> listing (events)
             engagement ==(Service Bus)==> notification -> email
             ai -> Gemini API   (the only service holding an LLM key)
```

### 1.1 Design principles
1. **AI is an enhancement layer, not a dependency.** Every AI feature has a non-AI fallback and a flag.
2. **Structured in, structured out.** Machine-consumed LLM output uses structured outputs (`messages.parse(output_format=PydanticModel)`), validated by Pydantic.
3. **Grounding over generation.** The LLM states only facts present in supplied context; cites them.
4. **One gateway.** All model calls go through the ai service's `LLMClient` (ADR-0004); no other service holds an LLM key.
5. **Own your data.** Each microservice owns its store; others use its API or its events (architecture.md §3).
6. **Measure everything AI does.** Every call is logged with tokens, latency, cost, prompt version.

### 1.2 Request flow example — NL search
```
Browser -> gateway: POST /api/v1/search/nl        (rate limit check in Redis; AI endpoints fail closed)
gateway -> search:  proxy
search:             Redis cache lookup nl:<sha256(normalised query)>
search -> ai:       POST /internal/nl-parse     (Gemini Flash-Lite, JSON schema)   } in parallel
search -> ai:       POST /internal/embeddings   (query vector)                     }
search:             hybrid SQL on its own read model: filters + cosine + filter fit + freshness
search -> browser:  { interpreted_filters, assumptions, items, meta.mode = ai | fallback }
```

---

## 2. Data model

### 2.1 Entity relationships
```
users 1──* listings 1──* listing_images
  │           │  1──* listing_documents 1──* document_chunks
  │           │  1──* enquiries *──1 users(buyer)
  │           *──* favourites *──1 users
  1──* saved_searches
  1──* ai_requests (nullable user)
```

### 2.2 DDL (logical model)
Tables are split across service-owned databases (architecture.md §3): `users` -> **identity**;
`listings`, `listing_images`, `listing_documents`, `audit_log` -> **listing**; a denormalised
`search_listings` projection -> **search**; `document_chunks` -> **ai**. `enquiries`, `favourites`,
`saved_searches` and `ai_requests` are **Cosmos DB containers** (ADR-0012), shown here as SQL only to
document their fields. Cross-service foreign keys below are logical, not enforced. Locally, location is
stored as `lat`/`lng` floats (PostGIS is a later option).
```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TYPE user_role        AS ENUM ('buyer','agent','admin');
CREATE TYPE listing_status   AS ENUM ('draft','published','unpublished','archived');
CREATE TYPE listing_type     AS ENUM ('sale','rent');
CREATE TYPE property_type    AS ENUM ('apartment','independent_house','villa','plot','commercial');
CREATE TYPE furnishing       AS ENUM ('unfurnished','semi_furnished','fully_furnished');
CREATE TYPE pet_policy       AS ENUM ('allowed','not_allowed','unknown');
CREATE TYPE doc_status       AS ENUM ('uploaded','processing','ready','failed');
CREATE TYPE ai_feature       AS ENUM ('nl_search','describe','qa','eval_judge');

CREATE TABLE users (
  id             uuid PRIMARY KEY,
  email          citext UNIQUE NOT NULL,
  name           text,
  phone          text,                       -- PII: never sent to LLM
  role           user_role NOT NULL DEFAULT 'buyer',
  agent_verified boolean NOT NULL DEFAULT false,
  suspended_at   timestamptz,
  deleted_at     timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE listings (
  id                 uuid PRIMARY KEY,
  agent_id           uuid NOT NULL REFERENCES users(id),
  status             listing_status NOT NULL DEFAULT 'draft',
  listing_type       listing_type  NOT NULL,
  property_type      property_type NOT NULL,
  title              text NOT NULL CHECK (char_length(title) BETWEEN 10 AND 120),
  description        text CHECK (char_length(description) <= 5000),
  description_ai     boolean NOT NULL DEFAULT false,      -- AI-assisted flag
  price_minor        bigint NOT NULL CHECK (price_minor > 0),  -- sale price or monthly rent, paise
  deposit_minor      bigint,                                   -- rent only
  maintenance_minor  bigint,                                   -- per month
  currency           char(3) NOT NULL DEFAULT 'INR',
  bedrooms           smallint CHECK (bedrooms BETWEEN 0 AND 20),  -- 0 = studio/1RK
  bathrooms          smallint CHECK (bathrooms BETWEEN 0 AND 20),
  balconies          smallint,
  carpet_area_sqft   integer,
  builtup_area_sqft  integer,
  floor              smallint,
  total_floors       smallint,
  facing             text,                    -- 'north','east',...
  furnishing         furnishing,
  parking_covered    smallint DEFAULT 0,
  parking_open       smallint DEFAULT 0,
  pet_policy         pet_policy NOT NULL DEFAULT 'unknown',
  possession_date    date,
  year_built         smallint,
  amenities          text[] NOT NULL DEFAULT '{}',  -- controlled vocabulary (config/amenities.yaml)
  attributes         jsonb NOT NULL DEFAULT '{}',   -- rare extras
  address_line       text NOT NULL,
  locality           text NOT NULL,
  city               text NOT NULL,
  pincode            char(6),
  geo                geography(Point, 4326) NOT NULL,
  rera_id            text,
  search_text        tsvector GENERATED ALWAYS AS (
                       to_tsvector('english', coalesce(title,'') || ' ' || coalesce(description,'')
                                   || ' ' || locality || ' ' || city)) STORED,
  embedding          vector(1024),
  embedding_model    text,
  published_at       timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CHECK (carpet_area_sqft IS NULL OR builtup_area_sqft IS NULL OR carpet_area_sqft <= builtup_area_sqft)
);
-- Query: classic search filters on published listings
CREATE INDEX ix_listings_search ON listings (city, listing_type, bedrooms, price_minor) WHERE status = 'published';
CREATE INDEX ix_listings_geo       ON listings USING gist (geo);
CREATE INDEX ix_listings_amenities ON listings USING gin (amenities);
CREATE INDEX ix_listings_fts       ON listings USING gin (search_text);
CREATE INDEX ix_listings_locality  ON listings USING gin (locality gin_trgm_ops);
CREATE INDEX ix_listings_embedding ON listings USING hnsw (embedding vector_cosine_ops);

CREATE TABLE listing_images (
  id          uuid PRIMARY KEY,
  listing_id  uuid NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
  storage_key text NOT NULL,
  caption     text,
  position    smallint NOT NULL,
  width int, height int,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (listing_id, position)
);

CREATE TABLE listing_documents (
  id           uuid PRIMARY KEY,
  listing_id   uuid NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
  storage_key  text NOT NULL,
  filename     text NOT NULL,
  kind         text NOT NULL,           -- 'floor_plan','society_rules','brochure','other'
  status       doc_status NOT NULL DEFAULT 'uploaded',
  error        text,
  page_count   int,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE document_chunks (
  id           uuid PRIMARY KEY,
  document_id  uuid NOT NULL REFERENCES listing_documents(id) ON DELETE CASCADE,
  listing_id   uuid NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
  chunk_index  int NOT NULL,
  page_from    int, page_to int,
  content      text NOT NULL,
  token_count  int NOT NULL,
  embedding    vector(1024) NOT NULL,
  embedding_model text NOT NULL
);
-- Query: Q&A retrieval, always scoped to one listing
CREATE INDEX ix_chunks_listing   ON document_chunks (listing_id);
CREATE INDEX ix_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE enquiries (
  id          uuid PRIMARY KEY,
  listing_id  uuid NOT NULL REFERENCES listings(id),
  buyer_id    uuid REFERENCES users(id),
  name        text NOT NULL, phone text, email citext,
  message     text NOT NULL,
  source      text NOT NULL DEFAULT 'listing_page',   -- 'qa_unknown' when from Q&A fallback
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE favourites (
  user_id uuid REFERENCES users(id) ON DELETE CASCADE,
  listing_id uuid REFERENCES listings(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, listing_id)
);

CREATE TABLE saved_searches (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name text, raw_query text, filters jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai_requests (
  id              uuid PRIMARY KEY,
  feature         ai_feature NOT NULL,
  user_id         uuid REFERENCES users(id) ON DELETE SET NULL,
  listing_id      uuid REFERENCES listings(id) ON DELETE SET NULL,
  model           text NOT NULL,
  prompt_id       text NOT NULL,
  prompt_version  int  NOT NULL,
  input_tokens    int, output_tokens int, cache_read_tokens int,
  cost_usd_micros bigint,
  latency_ms      int,
  status          text NOT NULL,              -- 'ok','timeout','error','validation_failed','fallback'
  request_redacted  jsonb,                    -- PII-redacted, truncated
  response_redacted jsonb,
  feedback        smallint,                   -- -1 / 1
  feedback_comment text,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_ai_requests_feature_time ON ai_requests (feature, created_at);

CREATE TABLE audit_log (
  id uuid PRIMARY KEY, actor_id uuid, action text NOT NULL,
  target_type text, target_id uuid, reason text, created_at timestamptz NOT NULL DEFAULT now()
);
```

### 2.3 Data rules
- **Money:** integer paise. ₹80 lakh = `8_000_000_00` paise. Rent is monthly.
- **Lakh/crore:** 1 lakh = 100,000; 1 crore = 10,000,000 (INR, not paise). Conversion lives in `services/money.py`.
- **Amenities:** controlled vocabulary in `services/listing/app/schemas.py` (`AMENITIES`), mirrored in `services/ai/app/features/schemas.py` (e.g. `lift`, `gym`,
  `swimming_pool`, `power_backup`, `security_24x7`, `club_house`, `children_play_area`, `gated`).
  The NL search tool schema enum is generated from this file.
- **Listing embedding text:** `"{property_type} {bedrooms}BHK in {locality}, {city}. {title}. {description}. Amenities: {amenities}."`
  Re-embedded when any of those fields change (debounced 60 s).
- **Soft delete:** users (`deleted_at`) purged by job after 30 days; listings archived, never hard-deleted while enquiries exist.

---

## 3. API design (REST, base `/api/v1`)

### 3.1 Conventions
- JSON, `snake_case`; UUIDs as strings; timestamps ISO-8601 UTC.
- Money in responses: `{ "amount_minor": 800000000, "currency": "INR", "display": "₹80 L" }`.
- Pagination: cursor-based — `?cursor=<opaque>&limit=20` → `{ "items": [...], "next_cursor": "..." | null }`.
- Auth: `Authorization: Bearer <jwt>` sent by the SPA and verified by each service. Public endpoints accept anonymous.
- All public routes go through the gateway; the owning service per path is `ROUTES` in `services/gateway/app/main.py`.
- Every response has `X-Request-Id`.
- **Error envelope** (all 4xx/5xx):
```json
{ "error": { "code": "validation_error", "message": "Carpet area cannot exceed built-up area.",
             "details": [{ "field": "carpet_area_sqft", "issue": "gt_builtup" }], "request_id": "01J..." } }
```
Error codes: `validation_error` 422, `unauthorized` 401, `forbidden` 403, `not_found` 404,
`conflict` 409, `rate_limited` 429 (with `Retry-After`), `ai_unavailable` 503, `internal` 500.

### 3.2 Endpoint catalogue
| Method | Path | Purpose | Auth | Req |
|---|---|---|---|---|
| GET | `/health` | Liveness (+ `?deep=1` checks DB/Redis) | public | — |
| GET | `/me` | Current user | user | FR-6 |
| DELETE | `/me` | Request account deletion | user | FR-6.4 |
| GET | `/listings` | Classic search | public | FR-2 |
| GET | `/listings/{id}` | Detail | public* | FR-2 |
| POST | `/listings` | Create draft | agent | FR-1.1 |
| PATCH | `/listings/{id}` | Update | owner | FR-1.1 |
| POST | `/listings/{id}/publish` · `/unpublish` · `/archive` | Status transitions | owner | FR-1.1 |
| POST | `/listings/{id}/images` | Get presigned upload URL, then confirm | owner | FR-1.2 |
| PATCH | `/listings/{id}/images/order` | Reorder | owner | FR-1.2 |
| POST | `/listings/{id}/documents` | Upload doc → async processing | owner | FR-1.3 |
| GET | `/listings/{id}/documents` | Docs + status | owner | FR-1.3 |
| POST | `/search/nl` | AI NL search | public, rate-limited | FR-3 |
| POST | `/ai/describe` | Generate description draft | agent | FR-4 |
| POST | `/listings/{id}/qa` | Q&A turn (SSE) | public, rate-limited | FR-5 |
| GET | `/listings/{id}/qa/suggestions` | Starter questions | public | FR-5.4 |
| POST | `/ai/feedback` | 👍/👎 on an ai_request | public | FR-5.6 |
| POST | `/listings/{id}/enquiries` | Contact agent | public, rate-limited | FR-6.3 |
| GET/POST/DELETE | `/me/favourites` | Favourites | buyer | FR-6.2 |
| GET/POST/DELETE | `/me/saved-searches` | Saved searches | buyer | FR-6.2 |
| GET | `/agent/listings` · `/agent/enquiries` | Agent dashboard | agent | FR-1 |
| POST | `/admin/listings/{id}/moderate` | Unpublish/restore w/ reason | admin | FR-7.1 |
| GET | `/admin/ai-metrics?from&to&feature` | AI metrics | admin | FR-7.2 |
| GET | `/admin/ai-requests?feedback=-1` | Negative feedback review | admin | FR-7.3 |
| GET/PATCH | `/admin/flags` | Feature flags | admin | FR-7.4 |

\* Non-published listings visible only to owner/admin.

### 3.3 Key contracts

**`POST /search/nl`**
```json
// request
{ "query": "2bhk under 80 lakh near metro in pune, quiet area", "cursor": null, "limit": 20 }

// response 200
{
  "interpreted_filters": {
    "city": "Pune", "locality": null, "listing_type": "sale", "property_type": null,
    "bedrooms_min": 2, "bedrooms_max": 2,
    "price_min_minor": null, "price_max_minor": 800000000, "currency": "INR",
    "amenities": [], "pet_policy": null, "furnishing": null,
    "near": ["metro"], "soft_preferences": ["quiet area"]
  },
  "assumptions": ["Assumed you want to buy (not rent)."],
  "is_property_query": true,
  "items": [ { "id": "…", "title": "…", "price": {"amount_minor": 780000000, "currency": "INR", "display": "₹78 L"},
               "bedrooms": 2, "locality": "Kharadi", "city": "Pune", "thumbnail_url": "…",
               "match": { "score": 0.83, "reasons": ["2 BHK", "Under budget", "Semantic: quiet, park-facing"] } } ],
  "next_cursor": "…",
  "meta": { "mode": "ai" , "ai_request_id": "…", "cached": false }   // mode: "ai" | "fallback"
}
```

**`POST /ai/describe`**
```json
// request
{ "listing_id": "…", "tone": "warm", "length": "medium" }
// response 200
{ "title": "Sunny 2BHK with Balcony Views in Kharadi",
  "description": "…", "highlights": ["2 BHK, 950 sq ft carpet", "Covered parking for 1 car", "…"],
  "warnings": [], "ai_request_id": "…" }
```
Nothing is saved; the client PATCHes the listing after the agent accepts (`description_ai=true`).

**`POST /listings/{id}/qa`** — `Accept: text/event-stream`
```json
// request
{ "question": "What is the monthly maintenance?",
  "history": [ { "role": "user", "content": "…" }, { "role": "assistant", "content": "…" } ] }  // ≤ 6 turns
```
```
event: token      data: {"text": "The monthly maintenance is ₹3,500 "}
event: token      data: {"text": "[S1]."}
event: citations  data: {"sources": [{"id": "S1", "type": "listing_field", "label": "Maintenance"}]}
event: done       data: {"ai_request_id": "…", "answer_status": "answered"}   // answered | unknown | refused
event: error      data: {"code": "ai_unavailable", "message": "…"}
```

**`GET /listings`** (classic) query params:
`city, locality, listing_type, property_type, price_min, price_max (rupees), bedrooms (multi), furnishing,
amenities (multi, AND), pet_policy, bbox=minLng,minLat,maxLng,maxLat, sort=relevance|price_asc|price_desc|newest, cursor, limit`.

---

## 4. GenAI layer (`services/ai/app/`)

### 4.1 Modules
| Module | Responsibility |
|---|---|
| `llm/base.py` | `LLMClient` protocol, `CallContext`, `Parsed`, `StreamResult`, `AIRefused`, `AIOutputInvalid` |
| `llm/gemini_client.py` | Gemini implementation (`google-genai`): `parse()` via `generate_content` with `response_json_schema` + Pydantic validation, `stream()` via `generate_content_stream`; `thinking_level`, per-feature timeouts, retries on 408/429/5xx, safety-block handling, usage -> cost, request logging |
| `llm/fake.py` | Offline deterministic client (`AI_FAKE=true`) for local dev and tests |
| `embeddings.py` | `EmbeddingProvider`: `HashingEmbeddings` (offline) and `GeminiEmbeddings` (`gemini-embedding-001`, 768 dims, normalised) |
| `prompts/loader.py` + `prompts/*.v<N>.md` | Versioned prompts, YAML front-matter, Jinja2 (`StrictUndefined`), `untrusted` filter escapes tag-like input |
| `guardrails.py` | `sanitize`, `redact_pii`, `screen_intent`, `fair_housing_violations`, `unsupported_numbers`, `invalid_citations` |
| `features/nl_search.py`, `rules.py`, `schemas.py` | NL parse + deterministic post-processing; rule parser (fake/baseline) |
| `features/describe.py` | Description generator with post-checks and one regeneration |
| `features/qa.py` | RAG Q&A: intent screen -> retrieve (scoped to listing) -> stream -> citation validation |
| `ingestion.py` | Service Bus consumer: PDF -> pages -> chunks -> embeddings -> `document_chunks` |
| `telemetry_store.py`, `pricing.py` | AI request log in Cosmos DB (`ai-requests`, TTL), cost per call, feedback |

### 4.2 Model routing (config-driven, ADR-0004)
| Feature | Default model | max_tokens | Timeout | Other params | Rationale |
|---|---|---|---|---|---|
| NL search extraction | `gemini-3.1-flash-lite` | 1024 | 1.5 s (search waits 2 s) | JSON schema output | High volume, simple extraction, latency-critical |
| Description | `gemini-3.8-flash` | 4000 | 30 s | JSON schema output | Writing quality; room for thinking tokens |
| Q&A | `gemini-3.8-flash` | 2000 | 30 s | `thinking_level: low` (prompt front-matter) | Grounded answers, low latency |
| Eval judge (offline) | `gemini-3.1-pro-preview` | — | — | JSON schema output | Strongest reasoning; preview is fine offline |

No `temperature` is sent (Gemini 3.x defaults are recommended). Gemini applies **implicit caching** to
repeated prompt prefixes, so system prompts must stay byte-stable; check `cached_content_token_count`
in the AI request log. Thinking tokens (`thoughts_token_count`) are billed at the output rate.

### 4.3 Feature: NL search (FR-3)

**Pipeline**
```
query
 └─▶ guardrails.sanitize_query (trim, ≤300 chars, strip control chars, redact PII)
      └─▶ cache get  nl:{sha256(normalised query)} (flush on prompt change)  ──hit──▶ filters
           └─miss─▶ in parallel:
                 (a) ai: llm.parse(nl_search prompt, SearchFilters)          [timeout 1.5 s]
                 (b) embeddings.embed_query(query)                              [timeout 1.0 s]
           └─▶ post-process: normalise city/locality via gazetteer, lakh/crore → paise,
               clamp nonsense (price_min > price_max → swap), drop unknown amenities
           └─▶ cache set (TTL 24 h)
 └─▶ services.search.hybrid(filters, query_vec) → results
 └─▶ response (+ interpreted_filters, assumptions, meta.mode)
```

**`SearchFilters` (Pydantic) — passed as `output_format`; all fields required-but-nullable (`services/ai/app/features/schemas.py`)**
```python
class SearchFilters(BaseModel):
    is_property_query: bool
    city: str | None                      # one of supported cities, else None
    locality: str | None
    listing_type: Literal["sale", "rent"] | None
    property_type: PropertyType | None
    bedrooms_min: int | None = Field(None, ge=0, le=10)
    bedrooms_max: int | None = Field(None, ge=0, le=10)
    price_min_inr: int | None = Field(None, ge=0)   # rupees; converted to paise in post-process
    price_max_inr: int | None = Field(None, ge=0)
    furnishing: Furnishing | None
    pet_policy: Literal["allowed"] | None
    amenities: list[Amenity] = []          # enum from amenities.yaml
    near: list[Literal["metro","school","hospital","it_park","mall","railway_station","airport"]] = []
    soft_preferences: list[str] = []       # free text, used for semantic ranking only
    assumptions: list[str] = []            # human-readable, shown to user
```

**Hybrid ranking query (sketch)**
```sql
WITH candidates AS (
  SELECT l.*, 1 - (l.embedding <=> :qvec) AS sem
  FROM listings l
  WHERE l.status = 'published'
    AND (:city IS NULL OR l.city = :city)
    AND (:listing_type IS NULL OR l.listing_type = :listing_type)
    AND (:bmin IS NULL OR l.bedrooms >= :bmin) AND (:bmax IS NULL OR l.bedrooms <= :bmax)
    AND (:pmax IS NULL OR l.price_minor <= :pmax * 1.05)       -- 5% tolerance, penalised below
    AND (:amenities = '{}' OR l.amenities @> :amenities)
  ORDER BY l.embedding <=> :qvec
  LIMIT 200
)
SELECT *, (0.55 * sem
         + 0.25 * filter_score(...)          -- exact fit, over-budget penalty, locality match
         + 0.10 * near_score(geo, :near)     -- distance to nearest POI of requested type
         + 0.10 * freshness(published_at)) AS score
FROM candidates ORDER BY score DESC, id LIMIT :limit;
```
- `near` uses a `pois` table (metro stations, schools…) loaded from OpenStreetMap extracts; distance ≤ 1.5 km scores 1.0, decays to 0 at 5 km.
- Weights live in config and are tuned with the search eval set.

**Fallback (`meta.mode = "fallback"`):** if (a) fails/times out → Postgres full-text search on
`search_text` + vector similarity from (b); if (b) also fails → full-text only.

### 4.4 Feature: Description generator (FR-4)

**Input fact sheet** (built by `services/listings.fact_sheet(listing)`; excludes agent contact & address line):
```yaml
property_type: apartment
listing_type: sale
bedrooms: 2
bathrooms: 2
carpet_area_sqft: 950
floor: "7 of 14"
facing: east
furnishing: semi_furnished
parking: "1 covered"
amenities: [lift, gym, swimming_pool, power_backup, security_24x7]
locality: Kharadi
city: Pune
possession: ready_to_move
price: "₹78 L"
image_captions: ["Living room with large window", "Balcony overlooking garden"]
agent_notes: "Recently repainted. Society has EV charging."   # untrusted, wrapped
```
**Structured output** `DescribeOutput`: `{ title (≤ 80 chars), description, highlights: [3..6] }`.

**Post-checks** (`guardrails`):
1. `fact_check_numbers` — every number in the output must appear in the fact sheet (after unit normalisation).
2. `check_fair_housing` — blocklist + pattern match (see `docs/ai/guardrails.md`).
3. Length within ±25% of target.
On failure → one regeneration with the violation fed back; if still failing → return with `warnings[]` and highlight offending sentences in UI.

### 4.5 Feature: Listing Q&A — RAG (FR-5)

```
question (+ ≤6 turns history)
 └─▶ sanitize + redact PII + length check (≤1000 chars)
 └─▶ quick intent screen (rules): legal/financial advice? → canned refusal template, no LLM call
 └─▶ retrieve (scoped to listing_id):
       S1..Sn  listing fact sheet fields (always, as individually citable facts)
       D1..D6  top-6 document_chunks by cosine similarity (min similarity 0.3)
 └─▶ build prompt: system (qa.vN) + <listing_facts> + <document id="D1" page="3">…</document> + history + question
 └─▶ llm.stream(...)  → SSE tokens
 └─▶ after stream: parse [S#]/[D#] citations → validate_citations (must exist in context)
       invalid citation → strip + log; answer w/o any citation and not "unknown" → flag answer_status=unverified
 └─▶ log ai_request; emit citations + done
```
- **Chunking:** by page then by heading/paragraph, target 500–800 tokens, 80-token overlap;
  store page ranges for citation display ("Society rules, p.3").
- **Isolation:** retrieval SQL always includes `WHERE listing_id = :id` — tested explicitly.
- **Injection defence:** documents wrapped as data; system prompt says to ignore instructions inside
  them; output never contains URLs/emails/phones not in context (post-filter).
- **Suggestions (FR-5.4):** static list filtered by which fields/docs exist (no LLM call).

### 4.6 Prompt management
- File: `app/ai/prompts/<id>.v<N>.md` with front-matter (`id`, `version`, `model_config_key`, `owner`, `changelog`).
- Active version per prompt set in config (`AI_PROMPT_VERSION_QA=2`) — enables instant rollback.
- New version ⇒ eval report attached to PR. Full catalog + drafts: [ai/prompts.md](ai/prompts.md).

---

## 5. Asynchronous processing (Service Bus consumers — ADR-0011)

| Work | Trigger | Runs in | Steps | Failure handling |
|---|---|---|---|---|
| Index listing for search | `listing.published` / `listing.updated` | search | embedding text -> `ai /internal/embeddings` -> upsert `search_listings` | embed failure -> index without vector (FTS still works); handler error -> retry -> DLQ |
| Remove from search | `listing.unpublished` | search | delete row | idempotent |
| Ingest document | `listing.document_uploaded` | ai | Blob download -> pypdf per page -> ~450-word chunks, 60-word overlap -> embed -> replace chunks | unreadable/scanned PDF -> `failed` + reason; transient error -> retry -> DLQ |
| Document status | `ai.document_processed` | listing | set `ready` / `failed` + error | idempotent |
| Email agent | `engagement.enquiry_created` | notification | fetch agent + enquiry via internal APIs -> SMTP / ACS | retry -> DLQ |
| Image processing | upload request | listing (in request, threadpool) | EXIF strip, 1600 px + 400 px WebP -> Blob | 422 on corrupt image |
| Retention / deleted-user purge | schedule | Container Apps jobs (T4.7) | Cosmos TTL already expires AI logs | — |

All handlers are idempotent (keyed by aggregate id). Re-index everything by re-publishing listings (T2.10).

---

## 6. Frontend design (`web/` — React + Vite, ADR-0009)

### 6.1 Routes (React Router, client-rendered)
| Route | Page | Content |
|---|---|---|
| `/` | `Home` | Hero NL search box with rotating examples, popular localities |
| `/search?q=…` or `/search?city=…` | `Search` | NL mode (`POST /search/nl`) or classic mode (`GET /search`); chips, assumptions, "Show more" |
| `/listings/:id` | `ListingDetail` | Gallery, key facts, description, amenities, **Q&A panel**, enquiry form |
| `/login` | `Login` | Email -> one-time code (dev code shown locally) |
| `/agent/listings` | `AgentListings` | Agent's listings table + enquiries |
| `/agent/listings/new`, `/agent/listings/:id/edit` | `ListingEditor` | Form, amenities, photo/PDF upload, **AI description** panel, publish |
| `/me/saved` | `Saved` | Saved homes (cards) and saved searches (re-run or remove) |
| `/account` | `Account` | Email, account type, sign out, sign out of all devices |
| `/admin` | `Admin` | People: find by email, set role, verify agents; rotate sign-in keys |
| (later) `/admin/ai`, `/admin/moderation` | — | AI dashboard (T4.4), listing moderation (T4.3) |

### 6.2 Key components (`web/src/components`)
- `NLSearchBox` — input with rotating example placeholders; navigates to `/search?q=`.
- `FilterChips` — renders `interpreted_filters`; removing a chip converts the rest into classic params (no LLM call).
- `ListingCard` — price, BHK, area, locality, match reasons.
- `QAPanel` — POST + SSE reader (`lib/sse.ts`), streaming answer, citation chips, suggestions, feedback, "Ask the agent" on `unknown`.
- `DescriptionGenerator` — tone/length, optional agent notes, warnings, editable draft, explicit "Use this description".

### 6.3 State & data
- Server state: TanStack Query; the URL is the source of truth for search state.
- API access only via `lib/api.ts` (`/api/v1/*`, same origin through the Vite proxy / nginx). Types in `lib/types.ts` (generate from OpenAPI — T0.7).
- Auth: `lib/auth.tsx` context (OTP locally, MSAL / Entra External ID in Azure).
- Styling: Tailwind v4 with brand tokens in `index.css`; mobile-first.

### 6.4 Visual design
- **Palette** (`web/src/index.css` `@theme`): limewash `#F4F5F1` background, paper `#FFFFFF` panels,
  indigo ink `#1C2757` for text and primary buttons, slate `#5B6479` secondary text, rule `#DCDFD8` dividers,
  leaf `#2F6F5E` success, danger `#B42318`. **Haldi `#E9A31B` is reserved** for two things: what the AI understood
  (underlines, answer rule, source tags) and keyboard focus. Don't use it for decoration.
- **Type:** Mukta (Ek Type), 400–800, one family everywhere; it also covers Devanagari for future Hindi search.
  Prices use `tabular-nums`. Sentence case everywhere; no all-caps labels.
- **Signature element:** the search is a sentence. The hero is a large sentence-style input; results restate the
  AI's reading as an editable sentence (`FilterChips`), each part underlined in haldi and removable.
- **Structure:** image-first listing tiles without card chrome; facts as a ruled definition list; panels only
  where content is interactive (Q&A, enquiry, AI draft). Photo-less listings show the locality in large type
  on a per-city tint (`city-pune`, `city-bengaluru`, `city-mumbai`).
- **Motion:** only in response to user actions (streaming caret in Q&A); `prefers-reduced-motion` is respected.
- **Shared classes:** `.field`, `.field-label`, `.btn-primary`, `.btn-quiet`, `.link`, `.understood`. Reuse them instead of new ad-hoc styles.
- SEO: client-rendered; pre-rendering listing pages is tracked as T4.11.

---

## 7. Security (summary — full threat model in [security.md](security.md))
- **AuthN:** local — identity service email OTP -> JWT (HS256, `JWT_TTL_S`), verified by every service via `estate_common.auth`; Azure — Microsoft Entra External ID tokens (RS256/JWKS) (ADR-0009).
- **AuthZ:** dependency `require_role(...)` + ownership checks in services; tested per endpoint.
- **Rate limits (Redis sliding window):** `/search/nl` 30/min/IP · `/qa` 20/min/IP & 200/day/IP ·
  `/ai/describe` 60/h/agent · `/enquiries` 5/h/IP · auth endpoints 10/min/IP.
- **Uploads:** presigned PUT to private bucket; server validates MIME by magic bytes and size;
  PDFs parsed in worker with limits (pages ≤ 100, time ≤ 60 s).
- **PII:** phone/email redaction (regex + libphonenumber) before LLM calls and logs.
- **Headers:** CSP, HSTS, X-Frame-Options DENY, Referrer-Policy strict-origin.
- **Secrets:** env vars from secret manager in prod; never in repo; `NEXT_PUBLIC_*` must not hold secrets.

---

## 8. Observability
- **Logs:** structlog JSON: `ts, level, request_id, user_id?, route, status, latency_ms, feature?`.
- **Traces:** OpenTelemetry (FastAPI + SQLAlchemy + httpx instrumentation); LLM call = span with
  attributes `ai.model, ai.prompt_version, ai.input_tokens, ai.output_tokens`.
- **Metrics:** request rate/latency/errors per route; AI metrics from the Cosmos `ai-requests` container (tokens, cost, latency, status, feedback).
- **Dashboards:** API health; Search funnel; AI (volume, p50/p95 latency, cost/day, fallback rate, 👍 ratio).
- **Alerts:**
  | Alert | Condition | Severity |
  |---|---|---|
  | LLM error rate | > 5% for 5 min | page |
  | NL search fallback rate | > 20% for 15 min | warn |
  | Daily AI cost | > 120% of budget | warn |
  | API p95 | > 500 ms for 10 min | warn |
  | Doc processing failures | > 10% in 1 h | warn |

---

## 9. Configuration
Each service has a pydantic-settings class (`services/<svc>/app/config.py`) extending
`estate_common.settings.CommonSettings`. Local values come from the root `.env` (see `.env.example`);
in Azure, from Container Apps environment variables and Key Vault secret references.
Groups: core, auth, Service Bus / Storage / Cosmos connections, AI models / timeouts / prompt versions,
embeddings, ranking weights, Q&A retrieval, rate limits, feature flags
(`FEATURE_NL_SEARCH`, `FEATURE_AI_DESCRIBE`, `FEATURE_LISTING_QA`). Runtime flag overrides via admin UI: T4.5.

---

## 10. Deployment
| Env | Purpose | Infra | AI |
|---|---|---|---|
| local | dev | docker compose + Azure emulators (architecture.md §6) | `AI_FAKE=true` by default; real key optional |
| CI | tests | unit tests + compose-based smoke job | Fake client only |
| staging | QA, evals | Azure Container Apps + managed services | real, flags on |
| prod | users | Azure Container Apps + managed services | real, flags controlled |

- One image per service (`services/<svc>/Dockerfile`, build context = repo root); web -> Azure Static Web Apps.
- Migrations (Alembic per Postgres-backed service) run as a Container Apps job before rollout.
- Container Apps revisions for blue/green; prompt/model changes roll out via config, not images.
- CI (GitHub Actions): per-service lint -> unit tests -> image build (matrix over `services/*`) -> compose smoke test -> deploy staging.
  The eval workflow runs when `services/ai/app/prompts/**`, `services/ai/app/features/**` or model config change.

---

## 11. Testing strategy
| Level | Tool | Scope | Runs |
|---|---|---|---|
| Unit | pytest, vitest | services, guardrails, money/lakh parsing, schema validation, components | every push |
| Integration | pytest + testcontainers | API + real Postgres/pgvector/Redis, `FakeLLMClient` | every push |
| Contract | schemathesis | OpenAPI conformance | every push |
| E2E | Playwright | J1, J2 journeys; LLM faked at API via `AI_FAKE=true` | PR to main |
| AI evals | `evals/` | real models vs golden sets, gates in [ai/evals.md](ai/evals.md) | prompt/model change + nightly |
| Load | k6 | search 50 RPS, NL search 10 RPS | pre-launch |
| Security | ZAP baseline, red-team set | OWASP + prompt injection | pre-launch |

Test-data builders in `tests/fixtures/factories.py` (factory-boy).

---

## 12. Failure modes
| Failure | Detection | Behaviour |
|---|---|---|
| Gemini API down / 429 / 503 | error/timeout in gateway | NL search → fallback mode; describe → 503 `ai_unavailable` with retry hint; Q&A → "Assistant unavailable, ask the agent" |
| Embedding provider down | error in embed | NL search → FTS only; new docs stay `processing` and retry |
| LLM returns invalid tool JSON | Pydantic error | 1 retry with error message; then fallback |
| Hallucinated citation | `validate_citations` | strip citation, mark `unverified`, log |
| Doc parse fails | worker exception | status `failed` + reason shown to agent |
| Cost spike | cost alert | admin flips flag / lowers rate limits |
| Redis down | connection error | rate limit fails **closed** for AI endpoints, open for classic; cache bypassed |

---

## 13. Capacity & cost model (MVP estimates)
| Feature | Calls/day (est.) | Avg input tok | Avg output tok | Notes |
|---|---|---|---|---|
| NL search | 5,000 (≈ 40% cache hit → 3,000 LLM calls) | ~1,200 (mostly cached system prompt) | ~150 | gemini-3.1-flash-lite |
| Description | 300 | ~1,500 | ~400 | gemini-3.8-flash |
| Q&A | 2,000 turns | ~4,000 (facts + 6 chunks) | ~200 | gemini-3.8-flash |

Cost per call = tokens × model price (table in `ai/pricing.py`, kept in sync with ai.google.dev/gemini-api/docs/pricing; 3.8 Flash has introductory pricing until 2026-12-31).
Budget check is automated by the `ai_metrics_daily` view against NFR-3 targets.

---

## 14. Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Hallucinated listing facts | Med | High | Grounding prompt, fact check, citations, evals, "unknown" path |
| Prompt injection via docs/agent notes | Med | High | Untrusted wrapping, output filters, red-team evals |
| LLM cost overrun | Med | Med | Flash-Lite for volume, implicit caching, query cache, rate limits, alerts |
| LLM latency hurts UX | Med | Med | Streaming, timeouts, fallback, chips shown optimistically |
| Poor locality normalisation | High | Med | Gazetteer table per city + eval cases |
| Discriminatory generated text | Low | High | Fair-housing prompt rules + blocklist + eval |
| Vendor lock-in | Low | Med | Gateway + provider interfaces |
