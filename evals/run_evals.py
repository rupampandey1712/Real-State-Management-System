"""Eval runner (docs/ai/evals.md). Calls the running AI service over HTTP, so it measures exactly
what production code does — prompt, model, post-processing.

    python evals/run_evals.py --suite search [--ai-url http://localhost:8004] [--gate 0.9]

With AI_FAKE=true this scores the offline rule parser (a baseline). With AI_FAKE=false it scores
Gemini and costs money — check the case count first. Suites describe/qa follow the same shape (T2.9).
"""

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
PRICE_TOLERANCE = 0.02


def field_matches(field: str, expected, actual) -> bool:
    if field.startswith("price_") and expected is not None and actual is not None:
        return abs(actual - expected) <= expected * PRICE_TOLERANCE
    if isinstance(expected, list):
        return sorted(expected) == sorted(actual or [])
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.lower() == actual.lower()
    return expected == actual


def score_search_case(case: dict, filters: dict) -> tuple[int, int, list[str]]:
    correct, total, misses = 0, 0, []
    for field, expected in case["expected"].items():
        total += 1
        if field == "soft_preferences_excludes_pattern":
            ok = not any(re.search(expected, p, re.I) for p in filters.get("soft_preferences", []))
        else:
            ok = field_matches(field, expected, filters.get(field))
        correct += ok
        if not ok:
            misses.append(f"{field}: expected {expected!r}, got {filters.get(field, filters.get('soft_preferences'))!r}")
    return correct, total, misses


def run_search(ai_url: str) -> dict:
    cases = [json.loads(line) for line in (ROOT / "search" / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    correct = total = 0
    latencies, failures = [], []
    with httpx.Client(base_url=ai_url, timeout=30) as client:
        for case in cases:
            started = time.perf_counter()
            response = client.post("/internal/nl-parse", json={"query": case["query"]})
            latencies.append(time.perf_counter() - started)
            response.raise_for_status()
            c, t, misses = score_search_case(case, response.json()["filters"])
            correct, total = correct + c, total + t
            if misses:
                failures.append({"id": case["id"], "query": case["query"], "misses": misses})
    latencies.sort()
    return {
        "suite": "search",
        "cases": len(cases),
        "field_accuracy": round(correct / total, 4),
        "p95_latency_s": round(latencies[int(0.95 * (len(latencies) - 1))], 3),
        "failures": failures,
    }


def write_report(result: dict, gate: float) -> Path:
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    (reports / f"{result['suite']}-{stamp}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = [
        f"# Eval report — {result['suite']} — {stamp}",
        f"Cases: {result['cases']} · Field accuracy: {result['field_accuracy']:.1%} (gate ≥ {gate:.0%}) · p95: {result['p95_latency_s']}s",
        "",
        "## Failures",
        *[f"- **{f['id']}** `{f['query']}` — " + "; ".join(f["misses"]) for f in result["failures"]],
    ]
    path = reports / f"{result['suite']}-{stamp}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["search"], required=True)
    parser.add_argument("--ai-url", default="http://localhost:8004")
    parser.add_argument("--gate", type=float, default=0.90)
    args = parser.parse_args()

    result = run_search(args.ai_url)
    report = write_report(result, args.gate)
    passed = result["field_accuracy"] >= args.gate
    print(f"{result['suite']}: field accuracy {result['field_accuracy']:.1%} — {'PASS' if passed else 'FAIL'} (report: {report})")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
