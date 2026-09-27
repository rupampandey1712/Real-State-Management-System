# 0013 — Google Gemini as the LLM and embedding provider
- Status: Accepted
- Date: 2026-09-27
- Deciders: Product owner, tech lead
- Related: supersedes the *provider and model* choices in ADR-0004 (the single-gateway pattern stays); resolves ADR-0003

## Context
The product owner decided to use a **Gemini API key** instead of an Anthropic API key. The gateway
pattern from ADR-0004 (one `LLMClient` protocol, only the ai service talks to the provider) means the
switch touches one client class, config, pricing and docs — not feature code.

## Decision
- **SDK:** official Google Gen AI SDK for Python, `google-genai`, pinned `>=1.30,<3.0.0` (its README warns
  that 3.0.0 changes automatic function calling). Client: `genai.Client(api_key=GEMINI_API_KEY)`, async via `client.aio`.
- **Implementation:** `services/ai/app/llm/gemini_client.py` (`GeminiLLMClient`):
  - Structured output: `response_mime_type="application/json"` + `response_json_schema` built from the
    Pydantic model (nullable `anyOf` simplified to `type: [T, "null"]`), then **validated with Pydantic**.
  - Streaming: `client.aio.models.generate_content_stream`; history roles mapped `assistant → model`.
  - Thinking depth: `ThinkingConfig(thinking_level=…)` from prompt front-matter (`low|medium|high`), only when set.
  - Safety: `prompt_feedback.block_reason` or finish reasons `SAFETY / PROHIBITED_CONTENT / BLOCKLIST / SPII /
    RECITATION` → `AIRefused` → user-safe fallback.
  - Resilience: per-feature timeout (`asyncio` timeouts), retries with backoff on 408/429/5xx.
  - Caching: Gemini applies implicit caching to repeated prefixes — keep system prompts stable; `cached_content_token_count` is logged.
- **Model routing (config, `AI_MODEL_*`):**
  | Feature | Model | Why |
  |---|---|---|
  | NL search extraction | `gemini-3.1-flash-lite` | Cheapest stable model ($0.25 / $1.50 per 1M), low latency |
  | Descriptions | `gemini-3.8-flash` | Latest stable Flash; best writing quality per cost |
  | Listing Q&A | `gemini-3.8-flash`, `thinking_level: low` | Grounded answers with low latency |
  | Eval judge (offline) | `gemini-3.1-pro-preview` | Strongest reasoning; preview is acceptable for offline evals only |
- **Embeddings:** `gemini-embedding-001`, `output_dimensionality=768`, task types `RETRIEVAL_DOCUMENT` /
  `RETRIEVAL_QUERY`, L2-normalised client-side (the API doesn't normalise outputs below 3072 dims). One key for LLM and embeddings.
- **Azure note:** Gemini is not an Azure service. The key lives in Key Vault; egress to
  `generativelanguage.googleapis.com` must be allowed from the ai Container App. (Vertex AI is an
  option later via `genai.Client(vertexai=True, project=…, location=…)` — only the client constructor changes.)

## Consequences
- ➕ One provider/key for generation and embeddings; low cost (flash-lite for high-volume search).
- ➕ No feature code changed; `AI_FAKE=true` still runs everything offline.
- ➖ Data leaves Azure to Google — list Google as a processor (security.md §5); use the paid tier, whose
  data terms differ from the free tier (free-tier prompts may be used to improve Google products).
- ➖ `gemini-3.8-flash` pricing is introductory until 2026-12-31 (then doubles) — budget alerts must account for it.
- ➖ Prompts were written provider-neutral but must be re-validated with evals on Gemini (T2.11, T3a.6, T3b.7, T3c.9).
- ➖ `response_json_schema` supports a JSON Schema subset; very large/nested schemas can be rejected — keep output models flat.

## Alternatives considered
- **Anthropic Claude (ADR-0004 original)** — rejected per product direction.
- **Gemini via the Interactions API** (`client.interactions.create`) — newer surface; `generate_content` is
  stable, documented in the SDK README, and fits our stateless calls. Revisit if we need server-side conversation state.
- **Vertex AI** — better enterprise controls (VPC-SC, regional residency); consider for production if data residency requires it.

## Revisit when
Model deprecations are announced, eval gates fail on Gemini, or data-residency requirements change.
