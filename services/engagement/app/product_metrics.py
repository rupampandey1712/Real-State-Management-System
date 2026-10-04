"""Success metrics (requirements §9), measured from anonymous product events.

The SPA sends a handful of event types. They carry **no user id, email or listing contents** — only a random
per-tab session id (to tie a search to the listing view that followed it) and the fields below. Stored in
Cosmos `product-events` (pk /day, TTL 90 days). The rollup is pure and unit-tested.

| Metric (target)                                  | Computed from                                                      |
|--------------------------------------------------|--------------------------------------------------------------------|
| Search → listing-view CTR, NL vs classic (+20 %) | listing_viewed{from_search} per search_performed{mode}             |
| Share of searches using the NL box (≥ 40 %)      | search_performed{mode=ai or fallback} / all                        |
| Median agent time-to-publish (≤ 10 min)          | listing_published{minutes_to_publish}                              |
| Descriptions accepted with ≤ 20 % edits (≥ 60 %) | description_saved{edit_ratio}                                      |
| Q&A answered without agent contact (≥ 50 %)      | qa_session vs enquiry_sent{after_qa}                               |
| Q&A 👍 ratio (≥ 80 %), AI factual errors          | AI request log — Admin → AI (ai service)                           |
"""

from statistics import median
from typing import Literal

from pydantic import BaseModel, Field

EventType = Literal["search_performed", "listing_viewed", "listing_published", "description_saved", "qa_session", "enquiry_sent"]


class ProductEvent(BaseModel):
    model_config = {"extra": "forbid"}  # nothing beyond these fields is ever stored

    type: EventType
    session: str = Field(pattern=r"^[0-9a-f]{16,32}$", description="random per browser tab, not a user id")
    mode: Literal["ai", "fallback", "classic"] | None = None  # search_performed; listing_viewed (search it came from)
    from_search: bool | None = None  # listing_viewed
    minutes_to_publish: float | None = Field(None, ge=0, le=60 * 24 * 365)  # listing_published (first publish only)
    edit_ratio: float | None = Field(None, ge=0, le=1)  # description_saved: share of the AI draft's words changed
    after_qa: bool | None = None  # enquiry_sent


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def rollup(events: list[dict]) -> dict:
    by_type: dict[str, list[dict]] = {}
    for e in events:
        by_type.setdefault(e["type"], []).append(e)
    searches = by_type.get("search_performed", [])
    views = [v for v in by_type.get("listing_viewed", []) if v.get("from_search")]
    nl_searches = [s for s in searches if s.get("mode") in ("ai", "fallback")]
    classic_searches = [s for s in searches if s.get("mode") == "classic"]
    nl_views = [v for v in views if v.get("mode") in ("ai", "fallback")]
    classic_views = [v for v in views if v.get("mode") == "classic"]
    publish_minutes = [p["minutes_to_publish"] for p in by_type.get("listing_published", []) if p.get("minutes_to_publish") is not None]
    edits = [d["edit_ratio"] for d in by_type.get("description_saved", []) if d.get("edit_ratio") is not None]
    qa_sessions = len(by_type.get("qa_session", []))
    enquiries_after_qa = sum(1 for e in by_type.get("enquiry_sent", []) if e.get("after_qa"))

    ctr_nl, ctr_classic = _ratio(len(nl_views), len(nl_searches)), _ratio(len(classic_views), len(classic_searches))
    return {
        "searches": len(searches),
        "nl_search_share": _ratio(len(nl_searches), len(searches)),
        "ctr_nl": ctr_nl,
        "ctr_classic": ctr_classic,
        "ctr_lift": round(ctr_nl / ctr_classic - 1, 4) if ctr_nl is not None and ctr_classic else None,
        "listings_published": len(publish_minutes),
        "median_minutes_to_publish": round(median(publish_minutes), 1) if publish_minutes else None,
        "ai_descriptions_saved": len(edits),
        "ai_descriptions_light_edit_share": _ratio(sum(1 for r in edits if r <= 0.2), len(edits)),
        "qa_sessions": qa_sessions,
        "qa_without_agent_contact": round(1 - enquiries_after_qa / qa_sessions, 4) if qa_sessions else None,
        "targets": {
            "ctr_lift": 0.20, "nl_search_share": 0.40, "median_minutes_to_publish": 10,
            "ai_descriptions_light_edit_share": 0.60, "qa_without_agent_contact": 0.50,
        },
    }
