# 0015 — Token lifecycle: RS256 + JWKS, rotating refresh tokens, revocation
- Status: Accepted
- Date: 2026-09-27
- Deciders: Tech lead
- Related: refines ADR-0009 (auth), ADR-0014 (edge validation); docs/security.md

## Context
The first version used one HS256 shared secret across all services, 8-hour tokens in localStorage, and
no logout or revocation. Every service holding the signing secret could mint tokens, and a stolen token
stayed valid for hours.

## Decision
- **Signing:** the identity service signs RS256 access tokens with a key pair (`signing_keys` table).
  Other services and the gateway only hold **public** keys, fetched from
  `identity /.well-known/jwks.json` (discovery at `/.well-known/openid-configuration`).
- **Key rotation:** automatic every `SIGNING_KEY_ROTATION_DAYS` (30) or on demand (`POST /api/v1/admin/keys/rotate`).
  Retired keys stay in JWKS until tokens they signed have expired. Verifiers refetch JWKS when they see an unknown `kid`.
- **Access tokens:** 15 minutes; claims `sub, role, agent_verified, iss, aud, iat, exp, jti`. Held **in memory** in the SPA.
- **Refresh tokens:** opaque 256-bit random values, stored **hashed**, sent as an httpOnly, SameSite=Strict
  cookie scoped to `/api/v1/auth` (Secure outside local). Rotated on every use; presenting an
  already-rotated token revokes the whole token family (theft detection). 30-day lifetime.
- **Revocation (Redis):** `jwt:deny:{jti}` (logout of one session) and `jwt:revoked_before:{sub}` (logout
  everywhere, role change, suspension). Checked by the gateway and by every service. If Redis is down the
  check fails open — acceptable because access tokens live 15 minutes.
- **Production:** private keys move to Azure Key Vault (sign via Key Vault or load at startup with a
  managed identity), or the whole flow moves to Entra External ID per ADR-0009. Verifiers don't change —
  they only need a JWKS URL.

## Consequences
- ➕ Only identity can mint tokens; leaked service config can't forge sessions.
- ➕ Real logout, logout-everywhere and instant role changes.
- ➕ XSS can't read a stored token (none in localStorage); CSRF on refresh is limited by SameSite=Strict + path scope.
- ➖ More moving parts (key table, refresh table, Redis keys); covered by unit tests in identity and libs/common.
- ➖ Private keys in Postgres are acceptable locally only — Key Vault is required before production (T4.14).
