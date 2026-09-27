"""Google Gemini implementation of the LLM gateway (ADR-0013, pattern from ADR-0004).

- Structured output: `response_mime_type="application/json"` + `response_json_schema`, then validated
  with Pydantic (`Model.model_validate_json`) — the model's JSON is never trusted unvalidated.
- Streaming: `client.aio.models.generate_content_stream`, text chunks only (thought parts are skipped).
- Thinking depth via `thinking_level` from the prompt front-matter (only sent when set).
- Gemini applies implicit prompt caching to repeated prefixes; keep system prompts stable.
- Safety blocks / prompt blocks are surfaced as AIRefused.
- Every call is logged (tokens, cost, latency, status) to the AI request log (Cosmos DB).
"""

import asyncio
import copy
import time
from collections.abc import AsyncIterator

import structlog
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.config import settings
from app.llm.base import AIOutputInvalid, AIRefused, CallContext, Parsed, StreamResult, T
from app.prompts.loader import RenderedPrompt
from app.telemetry_store import AIRequestLog, ai_log
from estate_common.errors import AIUnavailable

log = structlog.get_logger(__name__)

TIMEOUTS = {
    "nl_search": settings.ai_timeout_search_s,
    "describe": settings.ai_timeout_describe_s,
    "qa": settings.ai_timeout_qa_s,
}
RETRYABLE_CODES = {408, 429, 500, 502, 503, 504}
BLOCKED_FINISH_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY"}


def gemini_schema(schema: dict) -> dict:
    """Simplify Pydantic's JSON schema for Gemini: inline $defs and turn
    `anyOf: [X, {"type": "null"}]` into X with a nullable type (the documented form)."""
    schema = copy.deepcopy(schema)
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            node = {k: walk(v) for k, v in node.items() if k not in {"title", "default"}}
            options = node.get("anyOf")
            if options and len(options) == 2 and {"type": "null"} in options:
                inner = next(o for o in options if o != {"type": "null"})
                merged = {**{k: v for k, v in node.items() if k != "anyOf"}, **inner}
                if isinstance(merged.get("type"), str):
                    merged["type"] = [merged["type"], "null"]
                if "enum" in merged:
                    merged["enum"] = [*merged["enum"], None]
                return merged
            return node
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(schema)


def _config(prompt: RenderedPrompt, **extra) -> types.GenerateContentConfig:
    kwargs = {"system_instruction": prompt.system, "max_output_tokens": prompt.max_tokens, **extra}
    if prompt.thinking_level:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=prompt.thinking_level)
    return types.GenerateContentConfig(**kwargs)


def _finish_reason(response) -> str | None:
    candidates = getattr(response, "candidates", None) or []
    reason = candidates[0].finish_reason if candidates else None
    return getattr(reason, "name", reason) if reason is not None else None


def _blocked(response) -> bool:
    feedback = getattr(response, "prompt_feedback", None)
    return bool(feedback and feedback.block_reason) or _finish_reason(response) in BLOCKED_FINISH_REASONS


def _history(history: list[dict]) -> list[dict]:
    return [{"role": "model" if h["role"] == "assistant" else "user", "parts": [{"text": h["content"]}]} for h in history]


class GeminiLLMClient:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key or None)

    async def _with_retries(self, ctx: CallContext, call):
        attempt = 0
        while True:
            try:
                return await asyncio.wait_for(call(), timeout=TIMEOUTS.get(ctx.feature, 30.0))
            except errors.APIError as exc:
                if exc.code in RETRYABLE_CODES and attempt < settings.ai_max_retries:
                    attempt += 1
                    await asyncio.sleep(0.5 * 2**attempt)
                    continue
                raise

    async def parse(self, prompt: RenderedPrompt, output_model: type[T], ctx: CallContext) -> Parsed[T]:
        entry = AIRequestLog.start(ctx, prompt)
        started = time.perf_counter()
        config = _config(
            prompt,
            response_mime_type="application/json",
            response_json_schema=gemini_schema(output_model.model_json_schema()),
        )
        try:
            response = await self._with_retries(ctx, lambda: self._client.aio.models.generate_content(
                model=prompt.model, contents=prompt.user, config=config,
            ))
        except TimeoutError as exc:
            await ai_log.finish(entry, started, status="timeout")
            raise AIUnavailable("The AI service timed out.") from exc
        except errors.APIError as exc:
            await ai_log.finish(entry, started, status="error", error=str(exc.code))
            log.error("llm_api_error", code=exc.code)
            raise AIUnavailable("The AI service returned an error.") from exc

        entry.record_usage(response.usage_metadata, getattr(response, "response_id", None))
        if _blocked(response):
            await ai_log.finish(entry, started, status="refused", stop_reason=_finish_reason(response))
            raise AIRefused()
        try:
            output = output_model.model_validate_json(response.text or "")
        except ValidationError as exc:
            await ai_log.finish(entry, started, status="invalid_output", stop_reason=_finish_reason(response))
            raise AIOutputInvalid(f"Structured output failed validation (finish={_finish_reason(response)}).") from exc
        await ai_log.finish(entry, started, status="ok", response=output.model_dump())
        return Parsed(output=output, request_id=entry.id)

    async def stream(
        self, prompt: RenderedPrompt, history: list[dict], ctx: CallContext, result: StreamResult
    ) -> AsyncIterator[str]:
        entry = AIRequestLog.start(ctx, prompt)
        result.request_id = entry.id
        started = time.perf_counter()
        contents = [*_history(history), {"role": "user", "parts": [{"text": prompt.user}]}]
        last = None
        try:
            async with asyncio.timeout(TIMEOUTS.get(ctx.feature, 30.0)):
                stream = await self._client.aio.models.generate_content_stream(
                    model=prompt.model, contents=contents, config=_config(prompt),
                )
                async for chunk in stream:
                    last = chunk
                    if chunk.text:
                        result.text += chunk.text
                        yield chunk.text
        except TimeoutError as exc:
            await ai_log.finish(entry, started, status="timeout")
            raise AIUnavailable("The AI service timed out.") from exc
        except errors.APIError as exc:
            await ai_log.finish(entry, started, status="error", error=str(exc.code))
            raise AIUnavailable("The AI service returned an error.") from exc

        if last is not None:
            entry.record_usage(last.usage_metadata, getattr(last, "response_id", None))
        blocked = last is not None and _blocked(last)
        result.stop_reason = "refusal" if blocked else (_finish_reason(last) if last else None)
        await ai_log.finish(entry, started, status="refused" if blocked else "ok",
                            response={"text": result.text}, stop_reason=result.stop_reason)
