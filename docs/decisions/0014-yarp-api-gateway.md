# 0014 — YARP (.NET 10) as the API gateway
- Status: Accepted
- Date: 2026-09-27
- Deciders: Product owner, tech lead
- Related: supersedes the custom Python gateway in ADR-0008; ADR-0015 (tokens); docs/architecture.md §2

## Context
The first gateway was a hand-written FastAPI reverse proxy with basic rate limiting. The product owner
asked for a standard gateway (YARP or Ocelot) plus production patterns at the edge: distributed rate
limiting, caching, JWT validation, fault tolerance and consistent error handling.

## Decision
- **YARP 2.3 on ASP.NET Core / .NET 10 (LTS)** in `services/gateway`. (.NET 9 was considered; it is
  short-term support ending November 2026, so .NET 10 LTS was chosen.)
- Routes and clusters live in `appsettings.json`; each route declares its policies:
  `AuthorizationPolicy` (`authenticated` / `agent` / `admin`), `RateLimiterPolicy`, `OutputCachePolicy`,
  `TimeoutPolicy`, `MaxRequestBodySize`. Anything not routed — including `/internal/*` — returns the 404 envelope.
- **JWT at the edge:** RS256 validation using the identity service's JWKS (auto-refresh on new `kid`),
  issuer/audience/lifetime checks, Redis revocation list. A request that *sends* a bad token is rejected
  even on public routes. Services still verify tokens themselves (defence in depth).
- **Rate limiting:** ASP.NET rate limiter with Redis sliding windows (`RedisRateLimiting`), partitioned per
  user (`sub`) or per IP; named policies for NL search, Q&A, describe, enquiries, auth. A broad per-IP
  global limiter runs in memory so a Redis outage never blocks the whole API; named policies fail closed.
- **Output cache in Redis** for anonymous GETs (search 30 s, listing detail 30 s, Q&A suggestions 5 min,
  media 6 h). Requests with `Authorization` are never cached.
- **Fault tolerance:** Polly via `ResilienceHandler` wrapped around YARP's upstream handler: 2 retries with
  jittered backoff for GET/HEAD only, and a circuit breaker per upstream (50 % failures over ≥ 10 calls in
  30 s → open 15 s). YARP active health checks (`/health/ready`, every 10 s) and passive health checks
  (transport failure rate) take unhealthy destinations out of rotation.
- **Errors:** global `IExceptionHandler`, a forwarder-error middleware and an authorization result handler
  all write the platform's standard error envelope with `request_id`.
- Also: request ids, security headers, request body limits, CORS, JSON logs, OpenTelemetry traces.

## Consequences
- ➕ Standard, well-documented gateway with built-in policies instead of hand-rolled code; 8 integration tests.
- ➕ Maps directly to Azure: Container Apps (same image) or Azure API Management in front later.
- ➖ Adds .NET to a Python codebase (one more toolchain in CI).
- ➖ Edge output cache can serve a listing change up to 30 s late; services' own caches are event-invalidated.

## Alternatives considered
- **Ocelot** — similar features via config; community-maintained and less actively developed.
- **Hardening the Python gateway** — no new language, but we would own every policy implementation.
- **Azure API Management only** — no local emulator; good for production edge, not for local dev.
