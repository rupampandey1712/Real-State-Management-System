# 0003 — Embedding provider
- Status: Accepted — resolved by ADR-0013: `gemini-embedding-001` at 768 dims (quality check still in T2.1)
- Date: 2026-09-27
- Deciders: Tech lead, product (for quality review)
- Related: FR-3, FR-5, design §4.1, ADR-0002

## Context
- Claude is our LLM (ADR-0004), but Anthropic does not offer a first-party embeddings endpoint;
  Anthropic's docs point to third-party providers such as Voyage AI.
- We embed (a) listing summaries for semantic search and (b) document chunks for Q&A retrieval.
- Requirements: strong English retrieval quality on short queries vs listing text; good
  multilingual/Hinglish quality for Phase 5; 1024 dimensions (schema); cost-effective; data not used for training.
- Volume estimate: initial backfill ~100k listings + ~1M chunks; ongoing ~5k queries/day.

## Decision (proposed)
Use a **hosted embedding API** behind the `EmbeddingProvider` interface (`app/ai/embeddings.py`).
Leading candidate: Voyage AI (general or multilingual model at 1024 dims). Final choice by the
mini-eval below.

## Evaluation plan (T2.1)
- Dataset: 50 NL queries × graded relevant listings from the seed set + 30 Q&A questions × gold chunks.
- Metrics: Recall@10 and nDCG@10 (search), Recall@6 (Q&A chunks), latency, cost per 1M tokens.
- Candidates: 2–3 hosted models + 1 open-source self-hosted baseline (e.g. bge-m3).
- Record results in this ADR, then change status to Accepted.

## Consequences
- Changing provider or dimension later requires a `reembed_all` backfill (supported; resumable).
- Adds a second external AI dependency — covered by fallback to full-text search.
- Queries and document text are sent to the provider — PII redaction applies (guardrails §2).

## Alternatives considered
- **Self-hosted open-source model** — no per-call cost and full data control, but needs GPU/CPU
  inference ops; reconsider if volume grows or data-residency rules require it.
- **Postgres full-text search only** — no semantic matching for soft preferences; fails FR-3.3.

## Revisit when
Embedding cost > 20% of AI spend, retrieval evals regress, or data-residency requirements change.
