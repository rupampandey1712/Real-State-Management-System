"""Integration event envelope and catalogue (docs/architecture.md §4).

Events are CloudEvents-shaped JSON. Consumers must be idempotent: the same event can be
delivered more than once (at-least-once delivery on Azure Service Bus).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

# Topics
LISTING_EVENTS = "listing-events"
AI_EVENTS = "ai-events"
ENGAGEMENT_EVENTS = "engagement-events"

# Event types
LISTING_PUBLISHED = "listing.published"
LISTING_UPDATED = "listing.updated"
LISTING_UNPUBLISHED = "listing.unpublished"
LISTING_DOCUMENT_UPLOADED = "listing.document_uploaded"
DOCUMENT_PROCESSED = "ai.document_processed"
ENQUIRY_CREATED = "engagement.enquiry_created"


class Event(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: str
    source: str
    subject: str  # the aggregate id, e.g. listing id
    time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any]
    # Request id of the API call that caused this event, so a trace can continue through Service Bus.
    correlation_id: str | None = None


def current_correlation_id() -> str | None:
    import structlog

    return structlog.contextvars.get_contextvars().get("request_id")
