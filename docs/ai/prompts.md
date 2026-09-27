# Prompt Catalog

> Prompts live as versioned files in `services/ai/app/prompts/` and are loaded by
> `services/ai/app/prompts/loader.py`. This catalog lists them and defines how to change them.
> Related: [evals.md](evals.md) · [guardrails.md](guardrails.md) · [../design.md §4](../design.md)

## 1. Catalog

| Prompt ID | Feature | Active | Model config key | Output | File | Eval suite |
|---|---|---|---|---|---|---|
| `nl_search` | NL search filter extraction | v1 | `AI_MODEL_SEARCH` (gemini-3.1-flash-lite) | structured `SearchFilters` | [nl_search.v1.md](../../services/ai/app/prompts/nl_search.v1.md) | `evals/search` |
| `describe` | Listing description | v1 | `AI_MODEL_DESCRIBE` (gemini-3.8-flash) | structured `DescribeOutput` | [describe.v1.md](../../services/ai/app/prompts/describe.v1.md) | `evals/describe` (T3a.1) |
| `qa` | Listing Q&A (RAG) | v1 | `AI_MODEL_QA` (gemini-3.8-flash) | streamed text with `[S#]`/`[D#]` citations | [qa.v1.md](../../services/ai/app/prompts/qa.v1.md) | `evals/qa` (T3c.3) |
| `judge_grounding` | Eval judge: groundedness | draft (§6) | `AI_MODEL_JUDGE` (gemini-3.1-pro-preview) | structured `Grade` | — | — |

Output models: `services/ai/app/features/schemas.py`.

## 2. File format

```markdown
---
id: qa                      # must match the file name
version: 1                  # must match the file name (qa.v1.md)
model_config_key: AI_MODEL_QA
max_tokens: 2000
thinking_level: low         # optional → ThinkingConfig(thinking_level=…); omit to use the model default
owner: ai-team
changelog: Initial version.
---
# System
…static instructions (sent as the system prompt with prompt caching)…

# User
…Jinja2 template with {{ variables }}…
```
- Rendering uses Jinja2 with `StrictUndefined` — a missing variable is an error, not an empty string.
- Every untrusted value (user text, agent notes, document text, captions) goes through `| untrusted`,
  which escapes `<`/`>` so input can't close our XML delimiters.
- The active version per prompt comes from config: `AI_PROMPT_VERSION_<ID>`.
- **No sampling parameters.** Gemini 3.x models are tuned for their default temperature; the loader has
  no such field. Tune behaviour with instructions, `thinking_level`, and examples.
- **Structured output, not function calling.** Machine-read output uses `response_mime_type="application/json"`
  + `response_json_schema` (from the Pydantic model), then Pydantic validation in `gemini_client.py`.

## 3. Writing rules
1. Explain *why* a rule exists — the model generalises better from reasons than from bare commands.
2. Put stable content first (system prompt) so it caches; variable content goes in the user turn.
3. Separate data from instructions with XML tags: `<listing_facts>`, `<document>`, `<agent_notes>`, `<query>`.
4. Prefer 3–6 diverse examples over long rule lists for extraction tasks.
5. Always define the "nothing to do" path (non-property query, unknown answer).
6. Never put secrets, user PII, timestamps or request ids in the system prompt (they break caching and leak data).
7. Keep prompts calm and direct — no ALL-CAPS or "CRITICAL" emphasis; current models follow plain instructions well.

## 4. Change process
1. Copy the active file to `<id>.v<N+1>.md` — never edit a released version. Update `version` and `changelog`.
2. Run the suite: `python evals/run_evals.py --suite <suite>` against an ai service started with
   `AI_PROMPT_VERSION_<ID>=<N+1>` and `AI_FAKE=false` (costs money — check case count first).
3. Compare with the baseline in `evals/baselines/`; attach both reports to the PR.
4. Merge; switch `AI_PROMPT_VERSION_<ID>` in staging, then prod. **Rollback = revert the number and restart the ai service.**
5. Flush the NL search cache after changing `nl_search`: `redis-cli --scan --pattern 'nl:*' | xargs redis-cli del`.
6. Update the table in §1. Use the `/new-prompt-version` command to automate steps 1–3.

## 5. Model-specific notes (Gemini, verified 2026-09 against ai.google.dev)
| Model | Notes for prompt authors |
|---|---|
| `gemini-3.1-flash-lite` | Cheapest stable model; keep extraction prompts example-driven; flat schemas |
| `gemini-3.8-flash` | Thinking always on (`low`/`medium`/`high`, default `medium`); thinking tokens are billed as output — leave room in `max_tokens` |
| `gemini-3.1-pro-preview` | Preview model — offline judge only, never in the request path |
| `gemini-embedding-001` | Max 2,048 input tokens per text; we request 768 dims and normalise |

## 6. Draft: `judge_grounding.v1.md` (evals only — task T2.9)

```markdown
---
id: judge_grounding
version: 1
model_config_key: AI_MODEL_JUDGE
max_tokens: 8000
owner: ai-team
changelog: Initial version.
---
# System
You are a strict evaluator checking whether an assistant's answer about a property is fully
supported by the provided context.

Procedure:
1. Split the answer into atomic factual claims (ignore greetings and suggestions to contact the agent).
2. For each claim decide SUPPORTED (explicitly stated in the context) or UNSUPPORTED (absent or
   contradicted). Paraphrase and number formatting differences are fine; added specifics are not.
3. Check that each citation points to a source that actually supports its claim.
4. If the expected behaviour is "unknown", the answer passes only if it clearly says the information
   is not available and makes no factual claim about it.

# User
<context>{{ context | untrusted }}</context>
<question>{{ question | untrusted }}</question>
<expected_behaviour>{{ expected }}</expected_behaviour>
<answer>{{ answer | untrusted }}</answer>
```
Output model `Grade`: `{ grounded: bool, claims: [{text, verdict, source_ids}], citation_errors: [str], correct_unknown: bool | null, notes: str }`.
