"""Listing description generator (FR-4, docs/design.md §4.4)."""

from dataclasses import dataclass

from app import guardrails
from app.features.schemas import DescribeOutput
from app.llm import get_llm
from app.llm.base import CallContext
from app.prompts.loader import render

TONE_GUIDES = {
    "professional": "clear, factual and confident, with no hype",
    "warm": "friendly and inviting, focusing on everyday living",
    "luxury": "refined and elegant, emphasising premium features that are actually listed; avoid clichés like 'nestled'",
}
TARGET_WORDS = {"short": 60, "medium": 120, "long": 200}


@dataclass
class DescribeResult:
    output: DescribeOutput
    warnings: list[str]
    request_id: str


def check(output: DescribeOutput, source_text: str) -> list[str]:
    copy = f"{output.title}\n{output.description}\n" + "\n".join(output.highlights)
    problems = [f"Number not in listing facts: {n}" for n in guardrails.unsupported_numbers(copy, source_text)]
    problems += [f"Possible discriminatory wording: \"{s}\"" for s in guardrails.fair_housing_violations(copy)]
    if len(output.title) > 80:
        problems.append("Title is longer than 80 characters.")
    if not 3 <= len(output.highlights) <= 6:
        problems.append("Provide 3 to 6 highlights.")
    return problems


async def generate(facts_payload: dict, tone: str, length: str, agent_notes: str, ctx: CallContext) -> DescribeResult:
    notes = guardrails.redact_pii(guardrails.sanitize(agent_notes, 2000))
    source_text = "\n".join(f"{f['label']}: {f['value']}" for f in facts_payload["facts"]) + "\n" + notes
    variables = {
        "facts": facts_payload["facts"],
        "image_captions": facts_payload.get("image_captions", []),
        "agent_notes": notes,
        "tone_guide": TONE_GUIDES[tone],
        "target_words": TARGET_WORDS[length],
        "previous_violations": "",
    }
    llm = get_llm()
    result = await llm.parse(render("describe", **variables), DescribeOutput, ctx)
    problems = check(result.output, source_text)
    if problems:  # one regeneration with the problems fed back, then return with warnings
        variables["previous_violations"] = "; ".join(problems)
        result = await llm.parse(render("describe", **variables), DescribeOutput, ctx)
        problems = check(result.output, source_text)
    return DescribeResult(output=result.output, warnings=problems, request_id=result.request_id)
