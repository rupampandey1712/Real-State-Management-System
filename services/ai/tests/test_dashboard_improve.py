import json

from fastapi.testclient import TestClient

from app.dashboard import daily_metrics, to_eval_case
from app.features import improve, qa
from app.llm.base import CallContext

FACTS = {"facts": [{"id": "S1", "label": "Bedrooms (BHK)", "value": "2"},
                   {"id": "S2", "label": "Carpet area", "value": "950 sq ft"}]}


def log_doc(feature: str, day: str, latency: int, status: str = "ok", feedback=None, cost=1000) -> dict:
    return {"feature": feature, "created_at": f"{day}T10:00:00+00:00", "status": status, "latency_ms": latency,
            "input_tokens": 100, "output_tokens": 20, "thinking_tokens": 5, "cost_usd_micros": cost, "feedback": feedback}


def test_daily_metrics_groups_by_day_and_feature():
    docs = [log_doc("qa", "2026-10-03", ms, feedback=fb) for ms, fb in [(100, 1), (200, -1), (300, None), (4000, 1)]]
    docs += [log_doc("qa", "2026-10-03", 50, status="error"), log_doc("describe", "2026-10-02", 900)]
    rows = daily_metrics(docs)
    assert [(r["day"], r["feature"]) for r in rows] == [("2026-10-03", "qa"), ("2026-10-02", "describe")]
    qa_row = rows[0]
    assert qa_row["requests"] == 5 and qa_row["errors"] == 1 and qa_row["error_rate"] == 0.2
    assert (qa_row["thumbs_up"], qa_row["thumbs_down"]) == (2, 1)
    assert qa_row["latency_p50_ms"] == 200 and qa_row["latency_p95_ms"] == 4000
    assert qa_row["output_tokens"] == 125  # thinking tokens are billed as output
    assert qa_row["cost_usd"] == 0.005 and qa_row["avg_cost_usd"] == 0.001


def test_eval_case_export_keeps_only_redacted_text():
    doc = {"id": "qa." + "a" * 32, "feature": "qa", "listing_id": "L1", "prompt_id": "qa", "prompt_version": 1,
           "model": "m", "user_id": "secret-user", "request_redacted": "Call me on [REDACTED_PHONE]",
           "response_redacted": "Wrong answer", "feedback_comment": "Not in the brochure", "created_at": "2026-10-03"}
    case = to_eval_case(doc)
    assert case["prompt"] == "qa.v1" and case["expected"] == "review"
    assert "secret-user" not in json.dumps(case)


async def test_improve_returns_the_rewrite_without_warnings_for_clean_text():
    draft = "Spacious 2 BHK with 950 sq ft carpet area and lots of light."
    result = await improve.rewrite(FACTS, draft, "warm", CallContext(feature="improve"))
    assert draft in result.output.description and result.warnings == []


async def test_improve_warns_on_discriminatory_wording():
    draft = "Lovely 2 BHK home in a quiet lane. Vegetarians only, strictly."
    result = await improve.rewrite(FACTS, draft, "warm", CallContext(feature="improve"))
    assert any("discriminatory" in w for w in result.warnings)


def test_citation_excerpts_are_short():
    assert qa._excerpt("word " * 500).endswith(" …")
    assert len(qa._excerpt("word " * 500)) <= qa.EXCERPT_CHARS + 2
    assert qa._excerpt("Pets are allowed.") == "Pets are allowed."


def test_listing_text_check_flags_only_exclusionary_sentences():
    from app.main import app

    client = TestClient(app)
    response = client.post("/internal/guardrails/listing-text", json={"fields": {
        "title": "2 BHK in Baner", "description": "Bright home with a balcony. Bachelors not allowed.",
    }})
    assert response.status_code == 200
    assert response.json()["violations"] == [{"field": "description", "phrase": "Bachelors not allowed."}]
