---
description: Check that code and specs (requirements, design, tasks, ADRs) are consistent
argument-hint: "[optional area, e.g. 'search' or 'T3b']"
---
Audit consistency between the specs and the code. Scope: $ARGUMENTS (if empty, the whole repo).

Check:
1. Every endpoint in `docs/design.md` §3.2 exists in `services/*/app/main.py` (and the gateway `ROUTES` table) with matching auth, and there are no undocumented endpoints.
2. The DB models and migrations match the DDL in `docs/design.md` §2.2.
3. Every setting in each `services/*/app/config.py` and `libs/common/estate_common/settings.py` is in `.env.example` (or deliberately per-service), and the reverse.
4. Tasks marked `[x]` in `docs/tasks.md` actually meet their "Done when" criteria.
5. There are no `google.genai` imports outside `services/ai/app/llm/gemini_client.py` and `services/ai/app/embeddings.py`, and no model ID literals outside config. No service reads another service's database; every event type is in `estate_common/events.py`, `infra/local/servicebus/Config.json` and `docs/architecture.md` §4.
6. Every prompt file in `services/ai/app/prompts/` is listed in `docs/ai/prompts.md`, with the correct active version.
7. The code doesn't contradict any accepted ADR.
8. `python scripts/check_api_sync.py` reports IN SYNC (every endpoint has UI and a gateway route; every UI call has an endpoint).

Output a table: Area | Finding | Evidence (file:line) | Suggested fix (code or doc). Don't change anything unless I ask.
