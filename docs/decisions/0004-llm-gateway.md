# 0004 — Single LLM gateway + Claude model routing
- Status: Accepted — provider and model table superseded by 0013 (Gemini); the gateway pattern below still applies
- Date: 2026-09-27
- Deciders: Tech lead
- Related: design §4.1–4.2, §8, guardrails §6

## Context
Several features call an LLM (NL search, descriptions, Q&A, eval judges). Without one entry
point we would get: inconsistent retries/timeouts, hard-coded model IDs, no cost tracking,
duplicated logging, and code that is hard to test without hitting the real API.

## Decision
1. **Provider:** Anthropic Claude via the official `anthropic` Python SDK (async client).
2. **Gateway:** all model calls live in the **ai service** (ADR-0008) behind the `LLMClient` protocol
   in `services/ai/app/llm/` (`AnthropicLLMClient`, `FakeLLMClient`), exposing:
   - `parse(prompt, OutputModel, ctx) -> Parsed[OutputModel]` — structured output via
     `messages.parse(output_format=PydanticModel)`, validated by the SDK. (Not forced tool choice:
     Opus 5.5 rejects forced `tool_choice`.)
   - `stream(prompt, history, ctx, result) -> AsyncIterator[str]` — `messages.stream()`
   - No `temperature`/`top_p`: current Sonnet/Opus models reject sampling parameters. Depth/latency
     is tuned with `output_config.effort` (not supported on Haiku 4.5, so the client skips it there).
3. **Model routing by feature via config** (never literals in feature code):
   | Config key | Default | Used for |
   |---|---|---|
   | `AI_MODEL_SEARCH` | `claude-haiku-4-5` | NL search extraction (fast, cheap, high volume) |
   | `AI_MODEL_DESCRIBE` | `claude-sonnet-5` | Listing copy (quality writing) |
   | `AI_MODEL_QA` | `claude-sonnet-5` | Grounded Q&A with citations |
   | `AI_MODEL_JUDGE` | `claude-opus-5-5` | Offline eval judging |
4. **Cross-cutting behaviour in the gateway:** per-feature timeouts; up to 2 retries with jittered
   backoff on 429/5xx/overloaded; prompt caching on system prompts; token + cost accounting;
   AI request logging with PII-redacted payloads (Cosmos DB, ADR-0012); OpenTelemetry span per call;
   `stop_reason == "refusal"` handled explicitly.
5. **Testability:** `FakeLLMClient` implements the same protocol from fixtures; `AI_FAKE=true`
   selects it. Unit/integration tests never call the real API.

## Consequences
- ➕ Model upgrades = config change + eval run; no feature code changes.
- ➕ Cost, latency and quality visible per feature and prompt version.
- ➕ A second provider could be added behind the same protocol if ever needed.
- ➖ One more abstraction — keep it thin; no generic "chain" framework.

## Alternatives considered
- **Call the SDK directly in each feature** — rejected (above problems).
- **LangChain / LlamaIndex** — large surface area and abstractions we don't need for three features; harder to debug.
- **Third-party LLM proxy (hosted)** — extra vendor and data hop; revisit if we go multi-provider.

## Revisit when
We add a second LLM provider, or the gateway grows beyond ~400 lines.
