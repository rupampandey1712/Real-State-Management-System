"""Transactional outbox (ADR-0016) for Postgres-backed services.

Instead of publishing to Service Bus after commit (which loses the event if the process dies in
between), a service writes the event into the `outbox` table *in the same transaction* as its state
change. OutboxRelay publishes pending rows and marks them sent. Delivery is at-least-once; the event
id is the Service Bus message id, so topic duplicate detection drops repeats, and consumers stay idempotent.
"""

import asyncio
import json
from datetime import UTC, datetime
from itertools import groupby

import structlog
from azure.servicebus import ServiceBusMessage
from azure.servicebus.aio import ServiceBusClient
from sqlalchemy import DateTime, Integer, String, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from estate_common.db import Base, Database
from estate_common.events import Event, current_correlation_id

log = structlog.get_logger(__name__)


class OutboxMessage(Base):
    __tablename__ = "outbox"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # = event id = Service Bus message id
    topic: Mapped[str] = mapped_column(String(100))
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


def add_event(session: AsyncSession, *, topic: str, event_type: str, subject: str, data: dict, source: str) -> Event:
    """Stage an event in the caller's transaction. It is published only if the transaction commits."""
    event = Event(type=event_type, source=source, subject=subject, data=data, correlation_id=current_correlation_id())
    session.add(OutboxMessage(id=event.id, topic=topic, event_type=event_type, payload=event.model_dump(mode="json")))
    return event


class OutboxRelay:
    def __init__(self, db: Database, connection_string: str, *, batch_size: int = 50, idle_s: float = 1.0):
        self._db = db
        self._conn = connection_string
        self._batch = batch_size
        self._idle = idle_s

    async def publish_pending(self) -> int:
        async with self._db.sessionmaker() as session:
            rows = list(await session.scalars(
                select(OutboxMessage)
                .where(OutboxMessage.published_at.is_(None))
                .order_by(OutboxMessage.created_at)
                .limit(self._batch)
                .with_for_update(skip_locked=True)  # several replicas can relay safely
            ))
            if not rows:
                return 0
            try:
                async with ServiceBusClient.from_connection_string(self._conn) as client:
                    for topic, group in groupby(sorted(rows, key=lambda r: r.topic), key=lambda r: r.topic):
                        async with client.get_topic_sender(topic_name=topic) as sender:
                            await sender.send_messages([
                                ServiceBusMessage(json.dumps(row.payload), message_id=row.id, subject=row.event_type,
                                                  content_type="application/json")
                                for row in group
                            ])
                now = datetime.now(UTC)
                for row in rows:
                    row.published_at = now
            except Exception as exc:  # broker down: keep rows pending, record why
                for row in rows:
                    row.attempts += 1
                    row.last_error = f"{type(exc).__name__}: {exc}"[:500]
                log.warning("outbox_publish_failed", count=len(rows), error=type(exc).__name__)
                await session.commit()
                return -1
            await session.commit()
            log.info("outbox_published", count=len(rows))
            return len(rows)

    async def run_forever(self) -> None:
        backoff = self._idle
        while True:
            try:
                published = await self.publish_pending()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("outbox_relay_error")
                published = -1
            if published > 0:
                backoff = self._idle
                continue
            backoff = min(backoff * 2, 30.0) if published < 0 else self._idle
            await asyncio.sleep(backoff)
