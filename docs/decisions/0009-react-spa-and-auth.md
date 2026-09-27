# 0009 — React SPA (Vite) instead of Next.js; auth via identity service / Entra External ID
- Status: Accepted — token details refined by 0015 (RS256, refresh rotation, revocation)
- Date: 2026-09-27
- Deciders: Tech lead, product owner
- Related: supersedes the frontend half of ADR-0001 and all of ADR-0005

## Context
The product owner chose React (not Next.js). Without a Node server there is no server-side
rendering and no Auth.js session layer, so authentication and SEO need new answers.

## Decision
- **Frontend:** React 19 + TypeScript + Vite, React Router, TanStack Query, Tailwind CSS. Built to
  static files, served by nginx locally and **Azure Static Web Apps** (or Blob + Front Door) in Azure.
  All API calls go to `/api/*` → gateway (same origin, so SSE and cookies are simple).
- **Auth, local:** the identity service issues JWTs after an email one-time code (Mailpit captures
  mail). HS256 shared secret, verified by every service via `libs/common/estate_common/auth.py`.
- **Auth, Azure:** Microsoft Entra External ID (customer identity) with MSAL in the SPA; services
  validate Entra-issued tokens (RS256/JWKS). Only `web/src/lib/auth.tsx` and `estate_common/auth.py`
  change. Roles (buyer/agent/admin) remain owned by the identity service.
- **Token storage:** in-memory + localStorage for local dev. For production prefer MSAL's session
  handling with short-lived tokens; never store long-lived refresh tokens in localStorage.
- **SEO:** listing pages are client-rendered. Mitigation (task T4.11): pre-render listing pages
  (static generation job to Blob) or add an SSR edge function if organic search traffic matters.

## Consequences
- ➕ Simple static hosting, cheap CDN, clear frontend/backend boundary.
- ➖ Weaker SEO than SSR out of the box — tracked as T4.11.
- ➖ Token in browser storage is XSS-sensitive: strict CSP, no `dangerouslySetInnerHTML`, React escaping.

## Alternatives considered
- **Next.js (ADR-0001)** — better SEO; rejected per product direction.
- **BFF with httpOnly session cookies** — stronger token security; can be added to the gateway later.
