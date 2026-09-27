# Tracing every API from start to finish

> How to follow any request from the browser through the gateway, the services, their databases and
> Service Bus events, and back. Every flow below was traced on the running stack (2026-09-27).
> The per-endpoint facts (handler, auth, gateway policies, dependencies, frontend caller) are in the
> generated [api-reference.md](api-reference.md). To start the stack: [getting-started.md](getting-started.md).

---

## 1. The three tracing tools

### 1.1 Request id (logs) — works across HTTP *and* events
Every request gets an `X-Request-Id` (yours if you send one — letters/digits, ≤ 64 chars — otherwise generated).
It is:
- returned in the response header `X-Request-Id` and in every error body (`error.request_id`);
- logged by the gateway (`HTTP POST /api/v1/... -> 200 in 26.8 ms (route listings-write)`);
- logged by every Python service as a `"event": "request"` line with `request_id`, `status`, `duration_ms`;
- **forwarded on service-to-service calls** (`ResilientClient` adds the header);
- **carried through Service Bus** as the event's `correlation_id`, and bound as `request_id` in the consumer's logs
  (`"event": "event_handled"`), including any HTTP calls the consumer makes.

```bash
# Pick an id, make the call, then grep every service for it
RID=mytrace1
curl -s -X POST localhost:8080/api/v1/search/nl -H "Content-Type: application/json" \
     -H "X-Request-Id: $RID" -d '{"query":"2 bhk in powai with gym"}' > /dev/null
docker compose logs --no-color --since 5m | grep "$RID"
```
Real output (trimmed) for a listing update — one id through the gateway, listing, the outbox, Service Bus,
both consumers and the embeddings call:
```
gateway-1  | HTTP PATCH /api/v1/listings/ca97…a4 -> 200 in 26.8 ms (route listings-write)
listing-1  | {"method": "PATCH", "path": "/api/v1/listings/ca97…", "status": 200, "event": "request", "request_id": "event1790505232"}
search-1   | {"topic": "listing-events", "subscription": "search", "event": "event_handled", "request_id": "event1790505232", "event_type": "listing.updated"}
ai-1       | {"method": "POST", "path": "/internal/embeddings", "status": 200, "event": "request", "request_id": "event1790505232"}
ai-1       | {"topic": "listing-events", "subscription": "ai", "event": "event_handled", "request_id": "event1790505232"}
```

### 1.2 Distributed traces (Aspire Dashboard → Application Insights in Azure)
Open **http://localhost:18888 → Traces**. Each browser request is one trace named `gateway: <METHOD> <path>`,
with spans from the gateway, the service it reached, and any services *that* called (W3C `traceparent` is
propagated by the ASP.NET/HttpClient instrumentation in the gateway and by FastAPI/httpx instrumentation in
Python). Filter by path (e.g. `search/nl`) and click a trace for the waterfall. Failed spans are marked red.
Health probes are deliberately not traced.

Traces and request ids complement each other: **traces show timing across HTTP hops; the request id also
follows the asynchronous Service Bus part**, which starts a new trace in the consumer.

### 1.3 State inspection
| Where | Command |
|---|---|
| Postgres (per service) | `docker compose exec postgres psql -U estate -d listing` (or `identity`, `search`, `ai`) |
| Outbox (pending events) | `select event_type, created_at, published_at, attempts, last_error from outbox order by created_at desc limit 10;` |
| Redis | `docker compose exec redis redis-cli --scan --pattern 'cache:*'` (see key map in §4) |
| Cosmos DB | http://localhost:1234 → `estateai` → `enquiries` / `favourites` / `saved-searches` / `ai-requests` |
| Blob | Azure Storage Explorer → Local emulator → `listing-media` |
| Email | http://localhost:8025 |
| Gateway view of upstreams | `curl localhost:8080/health/deep` |

---

## 2. What happens to *every* request (the common path)

```
Browser (web/src/lib/api.ts)
  │  fetch /api/v1/…  + Authorization: Bearer <in-memory access token> (+ Idempotency-Key on some POSTs)
  ▼
nginx :3000  (or Vite dev proxy :5173)      location /api/ → gateway:8080, buffering off (SSE)
  ▼
Gateway (YARP, services/gateway)            order of middleware in Program.cs:
  1. RequestIdMiddleware        accept/create X-Request-Id, log one line per request
  2. UseExceptionHandler        any exception → error envelope
  3. SecurityHeaders, CORS
  4. UseAuthentication          JWT RS256 via identity JWKS; revocation check in Redis
  5. EdgeTokenMiddleware        a *sent* but invalid/revoked token → 401 token_invalid (except /api/v1/auth/*)
  6. UseAuthorization           route AuthorizationPolicy: authenticated | agent | admin → 401/403 envelope
  7. UseRateLimiter             global per-IP (memory) + route RateLimiterPolicy (Redis sliding window) → 429
  8. UseOutputCache             route OutputCachePolicy, anonymous GET only → served from Redis if fresh
  9. UseRequestTimeouts         route TimeoutPolicy (default 30 s) → 504
 10. YARP forwarder             pick healthy destination; Polly retry (GET) + circuit breaker; → upstream
     ForwarderErrorMiddleware   upstream down / circuit open → 503 envelope
  ▼
FastAPI service (services/<svc>/app/main.py)
  1. request_id_middleware      bind request_id to logs; log one "request" line; echo header
  2. IdempotencyMiddleware      (listing, engagement) replay/409/422 for repeated Idempotency-Key
  3. dependencies               auth (estate_common.auth: JWKS verify + revocation), DB session
  4. handler                    business logic; DomainError → error envelope (estate_common.errors)
  5. side effects               Postgres / Cosmos / Redis / Blob / outbox event / internal HTTP (ResilientClient)
  ▼
Response back through the gateway (output cache stores it if cacheable) → browser
```

Error envelope everywhere: `{"error": {"code", "message", "details", "request_id"}}`.
Codes you'll see: `unauthorized`, `token_invalid`, `forbidden`, `not_found`, `validation_error`,
`rate_limited` (+ `Retry-After`), `idempotency_key_reused`, `request_in_progress`, `service_unavailable`,
`dependency_unavailable`, `ai_unavailable`, `upstream_timeout`, `internal`.

---

## 3. Flow-by-flow traces

Each flow lists the hops in order. `file:line` links point at the code; policies come from
`services/gateway/src/Gateway/appsettings.json`.

### 3.1 Sign in (OTP) → session
1. **UI** `pages/Login.tsx` → `lib/auth.tsx` `requestCode` → `POST /api/v1/auth/otp/request`
2. **Gateway** route `auth`, rate limit `auth` (10/min per IP). No token attached for `/auth/*`.
3. **identity** `request_otp` → `otp.create_code`: Redis `otp:{email}` (hash, 10 min), resets `otp_attempts:{email}`
   → SMTP to **Mailpit**. Locally the code is also returned as `dev_code`.
4. **UI** `verifyCode` → `POST /api/v1/auth/otp/verify` → identity checks Redis (max 5 attempts), upserts the
   user in Postgres `users`, creates a refresh token (Postgres `refresh_tokens`, hashed), signs an **RS256** access
   token with the active key (`signing_keys`), sets cookie `estate_refresh` (httpOnly, SameSite=Strict, path `/api/v1/auth`).
5. **UI** keeps the access token **in memory** (`lib/api.ts`), then `GET /api/v1/me` (route `me`, policy `authenticated`).

Trace it: Mailpit shows the code email; `select email, role from users;` in `identity`; `redis-cli get otp:<email>` (gone after success).

### 3.2 Page reload / token expiry → refresh
1. **UI** `AuthProvider` mount (or any 401 in `lib/api.ts`) → `refreshSession()` → `POST /api/v1/auth/refresh` (cookie sent automatically).
2. **identity** `refresh` → `tokens.rotate_refresh_token`: looks up the hash; if already rotated → **revokes the whole
   family** (theft detection) → 401; else issues a replacement in the same family, marks the old one revoked, new cookie + new access token.
3. **UI** retries the original request once with the new token.

Trace it: `select family_id, revoked_at, replaced_by from refresh_tokens order by created_at desc limit 5;`

### 3.3 Classic search
1. **UI** `pages/Search.tsx` (URL params, no `q`) → `GET /api/v1/search?city=…`
2. **Gateway** route `search`, output cache `public-short` (30 s, varies by query string, anonymous only) —
   a cache hit ends here and never reaches the service.
3. **search** `classic_search` → `TwoLevelCache("search")`, **versioned**: L1 (10 s, in-process) → L2 Redis `cache:search:v{n}:{params}` (60 s)
   → Postgres `search_listings` (filters, sort, cursor). Any listing event bumps `cachever:search`, invalidating all entries.

### 3.4 Natural-language search (AI)
1. **UI** `NLSearchBox` → `/search?q=…` → `pages/Search.tsx` → `POST /api/v1/search/nl`
2. **Gateway** route `search-nl`, rate limit `nl_search` (30/min per user/IP).
3. **search** `nl_search`, in parallel:
   - Redis `nl:{sha256(query)}` (24 h) → on miss **ai** `POST /internal/nl-parse` (2 s budget, no retry) →
     `features/nl_search.parse` → prompt `nl_search.v1` → **Gemini** (`gemini-3.1-flash-lite`) or the offline rule parser → post-processing → logged to Cosmos `ai-requests`;
   - **ai** `POST /internal/embeddings` (retried, circuit breaker) → query vector.
4. **search** `ranking.hybrid_search`: SQL filters + pgvector cosine order (HNSW) over up to 200 candidates → score
   = 0.55·semantic + 0.30·filter fit + 0.15·freshness → response with `interpreted_filters` and `meta.mode` (`ai` or `fallback`).
5. **UI** `FilterChips` renders the sentence; removing a part navigates to classic search (3.3) — no AI call.

In Aspire: one trace `gateway: POST /api/v1/search/nl` with gateway → search → ai spans.

### 3.5 Listing page + Q&A (streaming)
1. **UI** `pages/ListingDetail.tsx` → `GET /api/v1/listings/{id}` → gateway route `listing-detail`, output cache 30 s →
   **listing** `get_listing`: anonymous → `TwoLevelCache("listing")` (L1 10 s, Redis `cache:listing:{id}` 5 min) → Postgres.
   Owners/admins bypass the cache (they see drafts).
2. `QAPanel` → `GET …/qa/suggestions` (route `qa-suggestions`, cached 5 min) → **ai** reads facts via
   **listing** `/internal/listings/{id}/facts` (cached in `TwoLevelCache("facts")`) and checks `document_chunks`.
3. Ask → `lib/sse.ts` `POST /api/v1/listings/{id}/qa` → gateway route `qa`, rate limit `qa`, timeout `ai-stream` (90 s), streamed unbuffered →
   **ai** `listing_qa` → `features/qa.answer`: guardrails (sanitize, PII redaction, advice screen) → retrieve top-6
   chunks from pgvector **scoped to this listing** → prompt `qa.v1` → Gemini stream → SSE events `token`… `citations` → `done`
   → citations validated → Cosmos `ai-requests` log.
4. 👍/👎 → `POST /api/v1/ai/feedback` → updates the Cosmos log item (`feature` partition from the id).

### 3.6 Create → publish a listing (outbox → Service Bus → search)
1. **UI** `pages/ListingEditor.tsx` "Save draft" → `POST /api/v1/listings` with `Idempotency-Key` (one per form).
2. **Gateway** route `listings-write`, policy `agent`.
3. **listing** `IdempotencyMiddleware` claims `idem:listing:{caller}:{key}` in Redis → `create_listing` → Postgres `listings`.
   A repeat with the same key gets the stored response + `Idempotent-Replayed: true`.
4. "Save and publish" → `PATCH` then `POST /api/v1/listings/{id}/publish` → in **one transaction**: status `published`
   + a row in `outbox` (`listing.published`, `correlation_id` = request id) → cache invalidated.
5. **OutboxRelay** (background task in listing) publishes pending rows to topic `listing-events` (message id = event id;
   duplicate detection on the topic) and sets `published_at`.
6. **search** consumer (subscription `search`) → `on_listing_event` → **ai** `/internal/embeddings` → upsert `search_listings`
   → `cachever:search` bumped. **ai** consumer (subscription `ai`) drops its cached fact sheet.

Trace it: `select event_type, correlation_id is not null, published_at from outbox order by created_at desc limit 3;` in `listing`;
grep the request id in `search` logs (`event_handled`).

### 3.7 Photo upload
`ListingEditor` → `POST /api/v1/listings/{id}/images` (multipart) → gateway route `upload-images` (policy `agent`, body ≤ 32 MB,
timeout 120 s) → **listing** `upload_image`: Pillow in a thread (EXIF stripped, 1600 px + 400 px WebP) → **Blob** `listing-media/listings/{id}/images/…`
→ Postgres `listing_images` → if published, `listing.updated` via outbox. Served back via `GET /api/v1/media/{key}` (route `media`, cached 6 h).

### 3.8 PDF upload → AI ingestion → status back (two events)
1. `ListingEditor` → `POST /api/v1/listings/{id}/documents` → **listing** validates `%PDF-`, size, count → **Blob** →
   Postgres `listing_documents` (status `processing`) + outbox `listing.document_uploaded` (same transaction).
2. **ai** consumer (subscription `ai`) → `DocumentIngestor.handle`: download from Blob → pypdf per page → ~450-word chunks
   → embeddings → replace `document_chunks` **and** outbox `ai.document_processed` (`ready`/`failed`) in one transaction.
3. ai's OutboxRelay → topic `ai-events` → **listing** consumer (subscription `listing`) sets the document status.
4. **UI** polls `GET /api/v1/listings/{id}/documents` every 4 s while any document is processing.

### 3.9 AI description
`DescriptionGenerator` → `POST /api/v1/ai/describe` → gateway route `ai-describe` (policy `agent`, rate limit `describe`, timeout 90 s)
→ **ai** `ai_describe`: facts from listing (owner check) → prompt `describe.v1` → Gemini (`gemini-3.8-flash`) JSON schema output →
Pydantic validation → guardrails (numbers must exist in the facts, fair-housing check) → one regeneration if needed → response with
`warnings`. Nothing is saved until the agent saves the form (3.6).

### 3.10 Enquiry → email to the agent
1. `ListingDetail` `EnquiryForm` → `POST /api/v1/listings/{id}/enquiries` with `Idempotency-Key` → gateway route `enquiries`, rate limit `enquiry` (5/h).
2. **engagement** idempotency → listing `/internal/listings/{id}/summary` (must be published) → Cosmos `enquiries`
   (partition `/agentId`, `eventPublished: false`) → publish `engagement.enquiry_created` (ids only, event id `enquiry-{id}`) → `eventPublished: true`.
   If publishing fails, the relay retries every 30 s.
3. **notification** consumer (subscription `notification`) → identity `/internal/users/{agent}` + engagement
   `/internal/enquiries/{agent}/{id}` → SMTP → **Mailpit**.
4. Agent sees it in `pages/AgentListings.tsx` → `GET /api/v1/agent/enquiries` (Cosmos query in the agent's partition).

### 3.11 Favourites and saved searches
`FavouriteButton` → `PUT/DELETE /api/v1/me/favourites/{id}` (optimistic UI) → gateway route `me-favourites` (`authenticated`) →
**engagement** → Cosmos `favourites` (partition `/userId`, id `{user}:{listing}`). `Saved.tsx` lists them and fetches each listing.
"Save this search" → `POST /api/v1/me/saved-searches` (idempotent) → Cosmos `saved-searches`.

### 3.12 Sign out, sign out everywhere, role change, key rotation
- `POST /api/v1/auth/logout` → identity revokes the refresh-token family + Redis `jwt:deny:{jti}` (until the token would expire) → cookie cleared.
  The gateway and every service now reject that access token.
- `POST /api/v1/auth/logout-all` → all refresh tokens revoked + `jwt:revoked_before:{user}` = now.
- Admin `Admin.tsx` → `POST /api/v1/admin/users/{id}/role` (route `admin-users`, policy `admin`) → Postgres update + `jwt:revoked_before:{user}`.
- `POST /api/v1/admin/keys/rotate` (route `admin-keys`) → new RS256 key; old key stays in `/.well-known/jwks.json` until its tokens expire;
  the gateway and services fetch the new key automatically on the first token with the new `kid`.

---

## 4. Redis key map

| Key | Owner | Meaning | TTL |
|---|---|---|---|
| `rl:{policy}:{user:<sub> or ip:<addr>}` (+ library suffixes) | gateway | sliding-window rate-limit counters | window |
| `gw-oc:*` | gateway | edge output cache | 30 s – 6 h |
| `otp:{email}`, `otp_attempts:{email}` | identity | sign-in code hash, attempt counter | 10 min |
| `jwt:deny:{jti}` | identity (read by all) | revoked access token | until token expiry |
| `jwt:revoked_before:{user}` | identity (read by all) | cut-off time for a user's tokens | access-token TTL + 60 s |
| `idem:{service}:{caller}:{key}` | listing, engagement | stored response for an Idempotency-Key | 24 h |
| `cache:{namespace}:…`, `cachever:{namespace}`, channel `cacheinv:{namespace}` | listing (`listing`), search (`search`), ai (`facts`) | two-level cache L2, version, invalidation broadcast | 1–5 min |
| `nl:{sha256}` | search | parsed NL query | 24 h |

## 5. Service Bus map

| Topic | Event | Published by (how) | Subscription → consumer |
|---|---|---|---|
| `listing-events` | `listing.published` / `.updated` / `.unpublished` | listing (outbox) | `search` → search index; `ai` → drop fact cache |
| `listing-events` | `listing.document_uploaded` | listing (outbox) | `ai` → ingestion |
| `ai-events` | `ai.document_processed` | ai (outbox) | `listing` → document status |
| `engagement-events` | `engagement.enquiry_created` | engagement (direct + relay) | `notification` → email |

Failures: a handler exception abandons the message → redelivered → dead-lettered after `MaxDeliveryCount`
(3–5). In the emulator, check `docker compose logs servicebus`; in Azure use Service Bus Explorer.

## 6. Debugging recipes

| Symptom | Where to look |
|---|---|
| 401 `token_invalid` | Token expired or revoked; the SPA refreshes once automatically. Check `jwt:deny:*` / `jwt:revoked_before:*` in Redis |
| 403 at the gateway | Route `AuthorizationPolicy` vs the token's `role` claim (decode the JWT) |
| 429 | Which `rl:` policy; `Retry-After` header says when |
| 503 `service_unavailable` | Gateway can't reach the service or its circuit is open: `curl localhost:8080/health/deep`, gateway logs `Circuit opened` |
| 503 `dependency_unavailable` | A service's call to another service failed or its breaker is open: grep the request id in both services |
| Listing not appearing in search | `outbox` row `published_at` null? `last_error`? Then search logs for `event_handled` with the request id |
| Document stuck "processing" | ai logs `document_ingestion_failed`; `outbox` in the `ai` DB; listing logs for `ai.document_processed` |
| Enquiry email missing | engagement doc `eventPublished`; notification logs; Mailpit |
| AI answer wrong / slow | Cosmos `ai-requests` item (prompt version, tokens, latency, status) via the `ai_request_id` in the response |
