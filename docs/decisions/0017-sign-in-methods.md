# 0017 — Sign-in methods: email magic link and Google, alongside the email code
- Status: Accepted
- Date: 2026-10-04
- Deciders: Tech lead
- Related: FR-6.1, ADR-0009 (auth), ADR-0015 (token lifecycle); services/identity/app/signin.py

## Context
FR-6.1 asks for sign-in "with email magic link or Google". The identity service only had a 6-digit email
code. ADR-0009 names Microsoft Entra External ID for production, which can federate Google, but it isn't
provisioned yet (T4.14), and the MVP needs both methods locally and in staging.

## Decision
- **Magic link.** `POST /auth/otp/request` sends one email with both a 6-digit code and a one-click link.
  The link carries a 256-bit random token in the URL **fragment** (`/login/magic#token=…`), so it never
  reaches servers, proxies or logs. The token is stored hashed in Redis for 15 min and consumed with an
  atomic `GETDEL` (single use). The SPA strips the fragment from the address bar before redeeming it.
- **Google.** The SPA loads Google Identity Services *only when* `GET /auth/providers` returns a client id,
  and posts the ID token to `POST /auth/google`. The identity service verifies the RS256 signature against
  Google's JWKS, the audience (`GOOGLE_CLIENT_ID`), the issuer and `email_verified`, then finds or creates
  the account by email. No Google access token or refresh token is ever requested or stored.
- All three methods end in the same place: our own RS256 access token + rotating refresh cookie (ADR-0015).
  Roles stay owned by the identity service.
- With `GOOGLE_CLIENT_ID` empty (the default), the Google button is hidden and the endpoint returns 401.

## Consequences
- ➕ Both FR-6.1 methods work without Entra; moving to Entra later only changes `signin.py` and `lib/auth.tsx`.
- ➕ No new dependency: PyJWT (already used) verifies Google tokens.
- ➖ Accounts are linked by email: a Google account and an email-link account with the same address are the
  same user. That is intended (both prove control of the address).
- ➖ The browser fetches Google's script when Google sign-in is enabled; a future CSP must allow
  `accounts.google.com`.

## Alternatives considered
- **Entra External ID now** — the production target, but not provisioned; blocks local development.
- **OAuth authorization-code flow on the server** — needs a client secret and a callback route; the ID-token
  flow is simpler for an SPA and gives us everything we need (a verified email).
