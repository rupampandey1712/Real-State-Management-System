"""Deterministic, offline LLM stand-in (AI_FAKE=true). Lets the whole stack run locally and in
CI without an API key. It is NOT a quality benchmark — real behaviour is measured by evals."""

import re
import time
from collections.abc import AsyncIterator

from app.features import rules
from app.features.schemas import DescribeOutput, ImproveOutput, SearchFilters
from app.llm.base import CallContext, Parsed, StreamResult, T
from app.prompts.loader import RenderedPrompt
from app.telemetry_store import AIRequestLog, ai_log

_WORD = re.compile(r"[a-z]+")
STOPWORDS = {"the", "is", "a", "an", "of", "in", "for", "what", "how", "does", "do", "there", "this", "it", "are", "any"}


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 2}


class FakeLLMClient:
    async def parse(self, prompt: RenderedPrompt, output_model: type[T], ctx: CallContext) -> Parsed[T]:
        entry = AIRequestLog.start(ctx, prompt, model="fake")
        started = time.perf_counter()
        if output_model is SearchFilters:
            output = rules.parse_query(prompt.variables["query"])
        elif output_model is DescribeOutput:
            output = self._describe(prompt.variables)
        elif output_model is ImproveOutput:
            output = ImproveOutput(description=f"[Offline rewrite — AI_FAKE=true] {prompt.variables['draft']}")
        else:
            raise NotImplementedError(f"No fake for {output_model.__name__}")
        await ai_log.finish(entry, started, status="ok", response=output.model_dump())
        return Parsed(output=output, request_id=entry.id)

    def _describe(self, variables: dict) -> DescribeOutput:
        facts = {f["label"]: f["value"] for f in variables["facts"]}
        bhk, locality, city = facts.get("Bedrooms (BHK)", ""), facts.get("Locality", ""), facts.get("City", "")
        highlights = [f"{label}: {value}" for label, value in list(facts.items())[:6] if label not in {"Locality", "City"}]
        body = " ".join(f"{label}: {value}." for label, value in facts.items())
        return DescribeOutput(
            title=f"{bhk} BHK in {locality}, {city}"[:80],
            description=f"[Offline draft — AI_FAKE=true] A {bhk} BHK home in {locality}, {city}. {body}",
            highlights=highlights[:6] or ["See listing details"],
        )

    async def stream(
        self, prompt: RenderedPrompt, history: list[dict], ctx: CallContext, result: StreamResult
    ) -> AsyncIterator[str]:
        entry = AIRequestLog.start(ctx, prompt, model="fake")
        result.request_id = entry.id
        started = time.perf_counter()
        question = _words(prompt.variables["question"])
        best, best_overlap = None, 0
        for fact in prompt.variables["facts"]:
            overlap = len(question & _words(fact["label"] + " " + fact["value"]))
            if overlap > best_overlap:
                best, best_overlap = f"The listing says {fact['label'].lower()}: {fact['value']} [{fact['id']}].", overlap
        for doc in prompt.variables["documents"]:
            for sentence in re.split(r"(?<=[.!?])\s+", doc["content"]):
                overlap = len(question & _words(sentence))
                if overlap > best_overlap:
                    best, best_overlap = f"According to {doc['filename']}: \"{sentence.strip()}\" [{doc['id']}]", overlap
        answer = best or "I don't have that information in this listing. You can ask the agent directly."
        for token in re.findall(r"\S+\s*", answer):
            result.text += token
            yield token
        result.stop_reason = "end_turn"
        await ai_log.finish(entry, started, status="ok", response={"text": result.text})
