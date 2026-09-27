# Security & Privacy

> Threat model and security checklist for EstateAI. Reviewed before launch (T4.8) and whenever
> auth, uploads, AI, or data handling change. AI-specific controls: [ai/guardrails.md](ai/guardrails.md).

## 1. Assets
| Asset | Sensitivity |
|---|---|
| User PII (name, email, phone), enquiries | High (DPDP personal data) |
| Agent accounts & listings | Medium (integrity matters — fake listings = fraud) |
| Uploaded documents (society rules, brochures) | Medium |
| API keys (Gemini, Storage, Cosmos, Service Bus, OAuth), JWT secret | Critical |
| AI logs (`ai_requests`) | Medium (redacted, but may contain context) |

## 2. Trust boundaries
```
[Browser SPA] ──HTTPS──▶ [gateway] ──JWT──▶ [microservices] ──▶ [Postgres/Cosmos/Redis/Blob/Service Bus]  (private network)
                                                   └──HTTPS──▶ [Google Gemini API: generation + embeddings]  (third party)
Untrusted inputs: all browser input, uploaded files, agent-written text, LLM output.
```

## 3. Threat model (STRIDE summary)
| Threat | Example | Controls |
|---|---|---|
| Spoofing | Stolen session; fake agent | httpOnly Secure cookies, short JWT TTL, agent verification before publish |
| Tampering | Editing another agent's listing | Ownership checks in services; tests per endpoint; audit_log |
| Repudiation | Admin unpublishes without trace | `audit_log` with actor + reason |
| Information disclosure | IDOR on drafts/enquiries; PII to LLM; secrets in client bundle | Authorisation tests, `redact_pii`, no secrets in `NEXT_PUBLIC_*`, signed URLs |
| Denial of service | Q&A spam burning tokens; huge PDFs | Rate limits, size/page caps, worker timeouts, budget alerts |
| Elevation of privilege | Buyer calls admin endpoints | `require_role`; deny-by-default router config |
| Prompt injection | Malicious PDF instructions | See guardrails G2/G3 |
| Malicious files | PDF exploits, polyglots | Magic-byte validation, parse in isolated worker, no execution, AV scan hook |
| SSRF | URLs in listing fields fetched server-side | Server never fetches user-supplied URLs |
| Scraping | Bulk listing/enquiry harvesting | Rate limits, agent contact revealed only via enquiry |

## 4. Controls checklist (OWASP ASVS L1-oriented)
**Auth & sessions**
- [ ] SPA token handling: MSAL/Entra in Azure (ADR-0009); no long-lived tokens in localStorage in prod; strict CSP against XSS
- [x] JWT: RS256 signed only by identity, 15-min access tokens, `iss`/`aud`/`exp` validated at the gateway and in every service, keys rotated via JWKS (ADR-0015)
- [x] Refresh tokens: hashed at rest, httpOnly + SameSite=Strict cookie scoped to `/api/v1/auth`, rotated on use, reuse revokes the family
- [x] Revocation: logout (per token), logout-all and role changes (per user) via Redis; checked at the edge and in services
- [ ] Private signing keys in Azure Key Vault before production (T4.14)
- [ ] Auth endpoints rate-limited at the gateway; OTP single-use, 10-min expiry, max 5 attempts (identity service)

**Authorisation**
- [ ] Every route declares auth requirement (test enumerates routes and fails if undeclared)
- [ ] Ownership check tests for listings, documents, enquiries, saved searches
- [ ] Suspended users blocked on write endpoints (DB check)

**Input & output**
- [ ] Pydantic validation on all inputs; max lengths everywhere
- [ ] SQL only via SQLAlchemy parameters (no string-built SQL)
- [ ] React escaping; no `dangerouslySetInnerHTML` (lint rule)
- [ ] CSP (no inline scripts; SPA served as static assets), HSTS, X-Content-Type-Options, frame-ancestors 'none'

**Files**
- [ ] Presigned uploads with content-length and content-type conditions
- [ ] Magic-byte validation; image re-encoding strips payloads and EXIF
- [ ] PDF parse limits: ≤ 100 pages, ≤ 60 s, memory limit in worker container
- [ ] Private bucket; signed GET URLs (10 min)

**Secrets & config**
- [ ] Secrets from secret manager; `.env` git-ignored; secret scanning in CI (gitleaks)
- [ ] Separate API keys per environment; least-privilege S3 credentials

**Dependencies**
- [ ] Dependabot/Renovate; `pip-audit` and `pnpm audit` in CI; lockfiles committed

**Logging & monitoring**
- [ ] No secrets/tokens/raw PII in logs (test with log capture)
- [ ] Security-relevant events logged: sign-in, role change, moderation, deletion

## 5. Privacy (DPDP Act 2023)
- **Notice & consent:** privacy notice at sign-up and on enquiry form; purpose: connecting buyers with agents.
- **Data minimisation:** phone optional for buyers; buyer PII never sent to AI providers.
- **Third-party processors:** Google (Gemini API — paid tier only, since free-tier data may be used to improve Google products), Microsoft Azure (hosting, email) — listed in privacy notice; use API terms under which inputs are not used for model training.
- **Rights:** access/export (`GET /me/export`, Phase 4), erasure (`DELETE /me` → purge ≤ 30 days).
- **Retention:** AI logs 30 days, enquiries 2 years, backups 30 days.
- **Breach:** follow runbook; notify Data Protection Board and affected users as required.

## 6. Security testing
| Test | When |
|---|---|
| Authorisation matrix tests (role × endpoint) | CI |
| gitleaks, pip-audit, pnpm audit | CI |
| OWASP ZAP baseline scan | pre-launch, monthly |
| AI red-team eval suite | on AI changes + nightly |
| Manual review of this checklist | pre-launch (T4.8) |
