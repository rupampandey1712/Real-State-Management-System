# Runbook — EstateAI Operations

> For on-call engineers. Each playbook: **Symptoms → Check → Mitigate → Follow-up**.
> Dashboards and alerts are defined in [design.md §8](design.md); the Azure alerts and availability tests are
> code in `infra/azure/modules/monitoring.bicep` and page the on-call action group.

## 0. Quick reference
| Action | How |
|---|---|
| Disable an AI feature | Admin → AI → "AI features on or off" (takes effect in ~5 s, no restart; ADR-0019). `FEATURE_*` env vars are only the defaults |
| Take a listing down / suspend an agent | Admin → Listings / People, with a reason (logged) |
| Roll back a prompt | Set `AI_PROMPT_VERSION_<ID>=<previous>` in config → restart the ai service (no build) |
| Switch a model | Set `AI_MODEL_<FEATURE>` → restart the ai service; run evals first unless emergency |
| Roll back a deploy | Redeploy previous image tag |
| Sign a user out everywhere | Admin role change, or `redis-cli SET jwt:revoked_before:<user id> $(date +%s) EX 1000` |
| Rotate JWT signing keys | `POST /api/v1/admin/keys/rotate` (admin); old key stays in JWKS until its tokens expire |
| See upstream health / circuits | `GET gateway /health/deep`; gateway logs `Circuit opened for …` |
| Events stuck | `SELECT count(*), max(attempts), max(last_error) FROM outbox WHERE published_at IS NULL;` in the listing / ai DB |
| Tail API logs for a request | filter `request_id=<id>` |
| Queue depth / dead letters | Service Bus Explorer (Azure portal) or emulator logs: `docker compose logs servicebus` |
| Re-run document processing | Re-upload the PDF (re-publish command: T2.10) |
| Re-embed everything | Re-publish all listings (T2.10); search re-indexes from events |
| Uptime / error budget | App Insights → Availability (`web is up`, `api is up`, 5 regions every 5 min) |

## 1. LLM error rate high (alert: > 5% for 5 min)
- **Symptoms:** NL search in fallback mode; describe returns 503; Q&A shows "unavailable".
- **Check:** `ai_requests` status breakdown last 15 min by model; Gemini API status (aistudio.google.com/status); 429 vs 5xx vs timeout.
- **Mitigate:**
  - 429 (rate limit): lower our rate limits temporarily; confirm account tier limits.
  - 5xx/overloaded: fallbacks are automatic — confirm they work; consider disabling Q&A flag if UX is poor.
  - Timeouts only: check network egress / DNS from api containers.
- **Follow-up:** incident note if > 30 min user impact.

## 2. AI cost spike (alert: daily cost > 120% budget)
- **Check:** cost by feature and by IP/user in `ai_requests`; cache hit rate for NL search; average input tokens (prompt change? retrieval returning too many chunks?).
- **Mitigate:** tighten rate limits; block abusive IPs; roll back recent prompt version; disable feature if needed.
- **Follow-up:** add budget test to evals if a prompt change caused it.

## 3. Reported wrong AI answer / fabricated fact
- **Check:** find the `ai_requests` row (admin → negative feedback, or by listing + time). Inspect context vs answer. Which prompt version/model?
- **Mitigate:** if systematic (several cases), disable the feature flag or roll back prompt version. If one listing, check its documents for injection/incorrect content; unpublish doc if malicious.
- **Follow-up:** export case to eval set; fix; pass gate; re-enable. Post-mortem in `docs/incidents/`.

## 4. Suspected prompt injection / abuse
- **Check:** search `ai_requests` for known injection phrases; documents uploaded recently by the agent.
- **Mitigate:** unpublish affected listing/doc; suspend agent if malicious (admin moderation, reason logged).
- **Follow-up:** add to red-team eval set.

## 5. Document processing stuck/failing (alert: > 10% failures in 1 h)
- **Check:** worker logs for `process_document`; embedding provider errors; PDF characteristics (scanned image PDFs have no text).
- **Mitigate:** restart worker; if provider down, jobs retry automatically; for scanned PDFs, inform agent (OCR is future work).

## 6. Search slow <a id="slow"></a>(alert `alert-<prefix>-latency`: average response > 300 ms for 15 min — NFR-8)
- **Check:** `pg_stat_statements` top queries; missing index; HNSW `ef_search`; DB CPU; cache hit rate; replica CPU
  (the search service is CPU-bound before the database is — docs/perf/phase1.md).
- **Mitigate:** scale replicas (`az containerapp update -n search --min-replicas 2`); add a read replica for search;
  reduce `RANK_CANDIDATES` temporarily.
- **Baseline:** 100k listings, 50 RPS, all cache misses → p95 150–205 ms on a laptop. Re-run `perf/k6/search.js` after fixes.

## 6a. Site or API down <a id="site-down"></a>(alert `alert-<prefix>-web-down` / `-api-down`, severity 0)
- **Symptoms:** availability test failing from 3+ of 5 regions.
- **Check:** `GET /api/health/deep` through Front Door, then the gateway FQDN directly (Front Door vs app problem);
  Container Apps revision status and restarts; Azure status page for Central India.
- **Mitigate:** roll back to the previous revision (`az containerapp revision activate`); if one dependency is down,
  see §7. If only `web` fails, redeploy the Static Web App from the last good build.
- **Follow-up:** incident note; log the downtime against the error budget below.

## 6b. Error budget <a id="error-budget"></a>(alert `alert-<prefix>-availability-budget`: API availability < 99.5 % over 24 h — NFR-1)
- **Target:** 99.5 % per month for web + API = at most **3 h 36 min** of downtime a month.
- **Check:** App Insights → Availability → `api is up`, last 30 days; which regions and times failed.
- **Mitigate:** if more than half the month's budget is spent, freeze risky releases (schema changes, model
  switches) until the month resets; prioritise the cause.
- **Report:** monthly uptime = average of `availabilityResults/availabilityPercentage` for `web is up` and `api is up`.

## 6c. Error rate <a id="errors"></a>(alert `alert-<prefix>-5xx`: more than 20 failed requests in 15 min)
- **Check:** App Insights → Failures, grouped by operation; gateway logs for `Circuit opened for …`; recent deploys.
- **Mitigate:** roll back the last revision if it started after a deploy; otherwise follow the dependency playbooks (§1, §7).

## 7. Database / Redis outage
- **Postgres down:** site mostly unavailable; restore from managed failover; verify migrations state.
- **Redis down:** caching and rate limiting degrade; AI endpoints fail closed (by design) → classic search still works; jobs pause.

## 8. Security incident / data breach
1. Contain: rotate affected secrets (JWT, API keys, S3), revoke sessions, block attacker.
2. Preserve logs.
3. Assess scope (which data, which users).
4. Notify: leadership; Data Protection Board and affected users per DPDP requirements.
5. Post-mortem and remediation tasks.

## 9. Routine operations
| Task | Frequency |
|---|---|
| Review 👎 AI feedback, export eval cases | Weekly |
| Check nightly eval report | Daily |
| Review AI cost vs budget | Weekly |
| Dependency updates | Weekly (automated PRs) |
| Backup restore drill | Quarterly |
| Rotate secrets | Every 90 days |

## 10. Incident template (`docs/incidents/YYYY-MM-DD-title.md`)
```markdown
# <Title>
- Date / duration:
- Severity:
- Impact (users, features):
- Timeline:
- Root cause:
- What went well / badly:
- Action items (with task IDs):
```
