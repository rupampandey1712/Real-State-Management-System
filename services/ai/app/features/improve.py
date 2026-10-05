"""'Improve my text' (FR-4.4): rewrite the agent's own description in a chosen tone (docs/design.md §4.4).

Same safety net as the generator: numbers must come from the draft or the fact sheet, fair-housing
wording is flagged, one regeneration with the problems fed back, then the draft is returned with warnings.
"""

from dataclasses import dataclass

from app import guardrails
from app.features.describe import TONE_GUIDES
from app.features.schemas import ImproveOutput
from app.llm import get_llm
from app.llm.base import CallContext
from app.prompts.loader import render

MAX_DRAFT_CHARS = 5000


@dataclass
class ImproveResult:
    output: ImproveOutput
    warnings: list[str]
    request_id: str


def check(output: ImproveOutput, source_text: str) -> list[str]:
    problems = [f"Number not in your text or the listing facts: {n}"
                for n in guardrails.unsupported_numbers(output.description, source_text)]
    problems += [f"Possible discriminatory wording: \"{s}\"" for s in guardrails.fair_housing_violations(output.description)]
    return problems


async def rewrite(facts_payload: dict, draft: str, tone: str, ctx: CallContext) -> ImproveResult:
    clean = guardrails.redact_pii(guardrails.sanitize(draft, MAX_DRAFT_CHARS))
    source_text = "\n".join(f"{f['label']}: {f['value']}" for f in facts_payload["facts"]) + "\n" + clean
    variables = {
        "facts": facts_payload["facts"],
        "draft": clean,
        "tone_guide": TONE_GUIDES[tone],
        "target_words": max(40, len(clean.split())),
        "previous_violations": "",
    }
    llm = get_llm()
    result = await llm.parse(render("improve", **variables), ImproveOutput, ctx)
    problems = check(result.output, source_text)
    if problems:
        variables["previous_violations"] = "; ".join(problems)
        result = await llm.parse(render("improve", **variables), ImproveOutput, ctx)
        problems = check(result.output, source_text)
    return ImproveResult(output=result.output, warnings=problems, request_id=result.request_id)
