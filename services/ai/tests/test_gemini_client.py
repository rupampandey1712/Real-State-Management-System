"""GeminiLLMClient against a mocked google-genai client (no network)."""

from types import SimpleNamespace

import pytest
from google.genai import errors, types

from app.features.schemas import SearchFilters
from app.llm.base import AIRefused, CallContext, StreamResult
from app.llm.gemini_client import GeminiLLMClient, _config, gemini_schema
from app.pricing import cost_usd_micros
from app.prompts.loader import render
from estate_common.errors import AIUnavailable

USAGE = SimpleNamespace(prompt_token_count=1200, candidates_token_count=150, thoughts_token_count=50,
                        cached_content_token_count=1000)


def response(text="", finish="STOP", block=None):
    return SimpleNamespace(
        text=text, response_id="r1", usage_metadata=USAGE,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=finish))],
        prompt_feedback=SimpleNamespace(block_reason=block) if block else None,
    )


class FakeModels:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def generate_content_stream(self, **kwargs):
        self.calls.append(kwargs)
        chunks = self.results

        async def gen():
            for chunk in chunks:
                yield chunk

        return gen()


def client_with(results) -> tuple[GeminiLLMClient, FakeModels]:
    client = GeminiLLMClient.__new__(GeminiLLMClient)
    models = FakeModels(results)
    client._client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return client, models


def nl_prompt():
    return render("nl_search", query="2bhk in pune", supported_cities=["Pune"])


VALID = SearchFilters.empty(city="Pune", bedrooms_min=2, bedrooms_max=2).model_dump_json()


async def test_parse_validates_structured_output_and_sends_schema():
    client, models = client_with([response(VALID)])
    parsed = await client.parse(nl_prompt(), SearchFilters, CallContext("nl_search"))
    assert parsed.output.city == "Pune"
    config = models.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert config.system_instruction.startswith("You convert")
    assert config.response_json_schema["properties"]["city"]["type"] == ["string", "null"]


async def test_safety_block_raises_refused():
    client, _ = client_with([response("", finish="SAFETY")])
    with pytest.raises(AIRefused):
        await client.parse(nl_prompt(), SearchFilters, CallContext("nl_search"))


async def test_retries_transient_errors_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.llm.gemini_client.asyncio.sleep", lambda *_: _noop())
    client, models = client_with([errors.ServerError(503, {"error": {"message": "overloaded"}}), response(VALID)])
    parsed = await client.parse(nl_prompt(), SearchFilters, CallContext("nl_search"))
    assert parsed.output.bedrooms_min == 2 and len(models.calls) == 2


async def test_non_retryable_error_becomes_ai_unavailable():
    client, _ = client_with([errors.ClientError(400, {"error": {"message": "bad"}})])
    with pytest.raises(AIUnavailable):
        await client.parse(nl_prompt(), SearchFilters, CallContext("nl_search"))


async def test_stream_yields_text_and_maps_history_roles():
    chunks = [response("Maintenance is "), response(None), response("₹3,500 [S2].")]
    client, models = client_with(chunks)
    prompt = render("qa", facts=[{"id": "S2", "label": "Maintenance", "value": "₹3,500"}], documents=[], question="q")
    result = StreamResult()
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    text = "".join([t async for t in client.stream(prompt, history, CallContext("qa"), result)])
    assert text == "Maintenance is ₹3,500 [S2]."
    assert [c["role"] for c in models.calls[0]["contents"]] == ["user", "model", "user"]
    assert models.calls[0]["config"].thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert result.stop_reason == "STOP"


def test_schema_has_no_anyof_or_defs():
    schema = gemini_schema(SearchFilters.model_json_schema())
    assert "$defs" not in schema and "anyOf" not in str(schema)
    assert schema["properties"]["listing_type"]["enum"] == ["sale", "rent", None]


def test_config_omits_thinking_when_not_set():
    assert _config(nl_prompt()).thinking_config is None


def test_cost_counts_cached_and_thinking_tokens():
    usage = {"input_tokens": 1200, "cached_tokens": 1000, "output_tokens": 150, "thinking_tokens": 50}
    # (200 × 0.75) + (1000 × 0.075) + (200 × 3.75) = 150 + 75 + 750
    assert cost_usd_micros("gemini-3.8-flash", usage) == 975


async def _noop():
    return None
