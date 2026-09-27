# 0005 — Auth.js on web, JWT verification in API
- Status: Superseded by 0009
- Date: 2026-09-27
- Deciders: Tech lead
- Related: FR-6.1, design §7, docs/security.md

## Context
We need email magic-link and Google sign-in, three roles (buyer, agent, admin), SSR pages that know
the user, and a Python API that must authorise every request. We don't want to build password
handling ourselves.

## Decision
- **Auth.js (NextAuth v5)** in `apps/web` handles sign-in flows (email magic link via SMTP provider, Google OAuth) and the session cookie (httpOnly, Secure, SameSite=Lax).
- User records live in the API database; Auth.js calls the API (server-to-server, shared secret) to upsert users on sign-in.
- For API calls, the Next.js server mints a **short-lived JWT (15 min, HS256)** containing `sub`, `role`, `agent_verified`; the browser never sees the signing secret.
- FastAPI verifies JWT in a dependency (`current_user`), then `require_role(...)` and service-level ownership checks enforce authorisation.
- Anonymous access is allowed for public endpoints (search, listing detail, Q&A) and rate-limited by IP.

## Consequences
- ➕ No password storage; mature OAuth handling.
- ➕ API stays stateless; easy to test with generated tokens.
- ➖ Role changes take up to 15 min to propagate via JWT (acceptable; suspension also checked in DB for write endpoints).
- ➖ Shared secret between web and API — stored in secret manager; plan migration to RS256 + JWKS if more clients appear.

## Alternatives considered
- **Hosted auth (Clerk, Auth0, Cognito)** — faster setup but vendor cost and PII outside our DB (DPDP considerations).
- **FastAPI-native auth (fastapi-users)** — would duplicate session handling in Next.js for SSR.

## Revisit when
Mobile apps or third-party API clients are added (→ RS256/JWKS, OAuth2 for API).
