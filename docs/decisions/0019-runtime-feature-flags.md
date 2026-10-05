# 0019 — Runtime feature flags in Redis
- Status: Accepted
- Date: 2026-10-04
- Deciders: Tech lead
- Related: FR-7.4, T4.5; libs/common/estate_common/flags.py

## Context
FR-7.4: admins must switch AI features on and off at runtime. Flags were environment variables, which
need a restart. The task left the choice open between Azure App Configuration and Redis.

## Decision
- One Redis hash, `feature_flags`, on the shared Azure Managed Redis (already a dependency of every
  service). `FeatureFlags` in `estate_common` reads it with a 5-second per-replica cache.
- Each service passes its **config defaults** (`FEATURE_*` env vars). They apply until an admin sets a
  value, and again whenever Redis is unreachable, so an outage never turns a feature *on*.
- The flag catalogue (`KNOWN_FLAGS`): `nl_search` (read by search), `ai_describe`, `ai_improve`,
  `listing_qa` (read by ai). The ai service's admin API writes them (`/api/v1/admin/ai/flags`), and
  `GET /api/v1/ai/features` tells the SPA what to hide.
- A service reads only the flags it owns. This is configuration, not another service's data, so it
  doesn't break the database-per-service rule.

## Consequences
- ➕ No new Azure resource; a toggle reaches every replica within ~5 s.
- ➖ No targeting, percentages or change history (changes are logged by the ai service). Move to Azure
  App Configuration if those are ever needed — only `flags.py` changes.
