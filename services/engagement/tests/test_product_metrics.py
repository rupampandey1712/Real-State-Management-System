import pytest
from pydantic import ValidationError

from app.product_metrics import ProductEvent, rollup

S = "0123456789abcdef"


def ev(type_, **fields):
    return {"type": type_, **fields}


def test_rollup_computes_every_success_metric():
    events = (
        [ev("search_performed", mode="ai")] * 6 + [ev("search_performed", mode="classic")] * 4
        + [ev("listing_viewed", from_search=True, mode="ai")] * 3 + [ev("listing_viewed", from_search=True, mode="classic")] * 1
        + [ev("listing_viewed", from_search=False)]
        + [ev("listing_published", minutes_to_publish=m) for m in (4, 8, 30)]
        + [ev("description_saved", edit_ratio=r) for r in (0.0, 0.1, 0.5, 0.2)]
        + [ev("qa_session")] * 4 + [ev("enquiry_sent", after_qa=True), ev("enquiry_sent", after_qa=False)]
    )
    m = rollup(events)
    assert m["searches"] == 10 and m["nl_search_share"] == 0.6
    assert m["ctr_nl"] == 0.5 and m["ctr_classic"] == 0.25 and m["ctr_lift"] == 1.0
    assert m["median_minutes_to_publish"] == 8
    assert m["ai_descriptions_light_edit_share"] == 0.75
    assert m["qa_without_agent_contact"] == 0.75


def test_rollup_of_nothing_is_empty_not_an_error():
    m = rollup([])
    assert m["nl_search_share"] is None and m["ctr_lift"] is None and m["median_minutes_to_publish"] is None


def test_events_cannot_carry_personal_data():
    with pytest.raises(ValidationError):
        ProductEvent(type="enquiry_sent", session=S, after_qa=True, email="priya@example.com")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ProductEvent(type="search_performed", session="not-a-random-id", mode="ai")
