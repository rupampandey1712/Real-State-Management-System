# 0006 — Server-Sent Events for Q&A streaming
- Status: Accepted
- Date: 2026-09-27
- Deciders: Tech lead
- Related: FR-5.5, design §3.3, §4.5

## Context
Q&A answers take several seconds to generate. Streaming tokens makes the experience feel instant
(first token < 2 s). Communication is one-directional per turn (question in → answer stream out).

## Decision
- Use **SSE** (`text/event-stream`) from FastAPI (`StreamingResponse` / `sse-starlette`) for
  `POST /listings/{id}/qa`, with typed events: `token`, `citations`, `done`, `error`.
- The web client consumes it with `fetch` + a stream reader (`lib/sse.ts`), since `EventSource` doesn't support POST bodies.
- Client disconnect cancels the upstream LLM stream (saves tokens).
- Citations are validated after the stream completes and sent as a final `citations` event;
  invalid inline citation markers are hidden client-side when the final list arrives.

## Consequences
- ➕ Plain HTTP; works through proxies/CDNs with buffering disabled (`X-Accel-Buffering: no`).
- ➕ Simple to test (read the event stream in integration tests).
- ➖ No bidirectional channel (not needed).
- ➖ Must ensure load balancer idle timeout > max answer time (30 s).

## Alternatives considered
- **WebSockets** — bidirectional but more complex infra/auth; unnecessary.
- **No streaming (wait for full answer)** — simpler, but 5–8 s blank wait hurts UX.

## Revisit when
We need real-time multi-party features (e.g. live agent chat).
