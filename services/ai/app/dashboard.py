"""Admin AI dashboard (FR-7.2, FR-7.3): daily per-feature metrics and feedback → eval cases.

Pure functions over AI request log documents (Cosmos `ai-requests`, see telemetry_store.py), so they are
unit-tested without Cosmos. The log keeps 30 days (TTL), which bounds what the dashboard reads.
"""

from collections import defaultdict


def _percentile(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def daily_metrics(docs: list[dict]) -> list[dict]:
    """Rows of {day, feature, requests, errors, error_rate, input_tokens, output_tokens, cost_usd,
    avg_cost_usd, latency_p50_ms, latency_p95_ms, thumbs_up, thumbs_down}, newest day first."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for doc in docs:
        groups[(doc["created_at"][:10], doc["feature"])].append(doc)
    rows = []
    for (day, feature), items in groups.items():
        errors = sum(1 for d in items if d.get("status") not in ("ok", None))
        cost_micros = sum(d.get("cost_usd_micros") or 0 for d in items)
        rows.append({
            "day": day,
            "feature": feature,
            "requests": len(items),
            "errors": errors,
            "error_rate": round(errors / len(items), 4),
            "input_tokens": sum(d.get("input_tokens", 0) for d in items),
            "output_tokens": sum(d.get("output_tokens", 0) + d.get("thinking_tokens", 0) for d in items),
            "cost_usd": round(cost_micros / 1_000_000, 4),
            "avg_cost_usd": round(cost_micros / 1_000_000 / len(items), 6),
            "latency_p50_ms": _percentile([d["latency_ms"] for d in items if d.get("latency_ms") is not None], 0.5),
            "latency_p95_ms": _percentile([d["latency_ms"] for d in items if d.get("latency_ms") is not None], 0.95),
            "thumbs_up": sum(1 for d in items if d.get("feedback") == 1),
            "thumbs_down": sum(1 for d in items if d.get("feedback") == -1),
        })
    return sorted(rows, key=lambda r: (r["day"], r["feature"]), reverse=True)


def to_eval_case(doc: dict) -> dict:
    """A 👎 interaction as a candidate eval case (docs/ai/evals.md §8). Request and response were redacted
    of emails, phone numbers and ID numbers when logged; a reviewer still checks the case before adding it."""
    return {
        "id": f"fb-{doc['id'].split('.', 1)[-1][:12]}",
        "source": "user_feedback",
        "feature": doc["feature"],
        "listing": doc.get("listing_id"),
        "prompt": f"{doc.get('prompt_id')}.v{doc.get('prompt_version')}",
        "model": doc.get("model"),
        "input_redacted": doc.get("request_redacted"),
        "bad_output_redacted": doc.get("response_redacted"),
        "user_comment": doc.get("feedback_comment"),
        "expected": "review",  # a human sets answer / unknown / refuse before the case joins a suite
        "logged_at": doc.get("created_at"),
    }
