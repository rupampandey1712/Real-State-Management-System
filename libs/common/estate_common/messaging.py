"""Azure Service Bus publish/consume helpers (works with the local emulator and Azure)."""

import asyncio
from collections.abc import Awaitable, Callable

import structlog
from azure.servicebus import ServiceBusMessage
from azure.servicebus.aio import ServiceBusClient

from estate_common.events import Event, current_correlation_id

log = structlog.get_logger(__name__)

EventHandler = Callable[[Event], Awaitable[None]]


class EventPublisher:
    def __init__(self, connection_string: str, source: str):
        self._conn = connection_string
        self._source = source

    async def publish(self, topic: str, event_type: str, subject: str, data: dict, *, event_id: str | None = None) -> Event:
        """Direct publish. Postgres-backed services use the outbox instead (estate_common.outbox);
        pass a stable event_id when re-publishing so Service Bus duplicate detection can drop repeats."""
        event = Event(type=event_type, source=self._source, subject=subject, data=data,
                      correlation_id=current_correlation_id())
        if event_id:
            event.id = event_id
        # A client per publish keeps this simple and robust to emulator restarts;
        # switch to a long-lived sender if publish volume grows.
        async with ServiceBusClient.from_connection_string(self._conn) as client:
            async with client.get_topic_sender(topic_name=topic) as sender:
                await sender.send_messages(
                    ServiceBusMessage(
                        event.model_dump_json(),
                        message_id=event.id,
                        subject=event.type,
                        content_type="application/json",
                    )
                )
        log.info("event_published", topic=topic, type=event_type, subject=subject)
        return event


async def consume_forever(
    connection_string: str,
    topic: str,
    subscription: str,
    handler: EventHandler,
    *,
    handled_types: set[str] | None = None,
) -> None:
    """Receive events forever. Failures abandon the message so Service Bus retries it,
    and after MaxDeliveryCount it moves to the dead-letter queue."""
    while True:
        try:
            async with ServiceBusClient.from_connection_string(connection_string) as client:
                async with client.get_subscription_receiver(topic_name=topic, subscription_name=subscription) as receiver:
                    log.info("consumer_started", topic=topic, subscription=subscription)
                    async for message in receiver:
                        try:
                            event = Event.model_validate_json(str(message))
                            # Continue the originating request's id so the consumer's logs join the same trace.
                            structlog.contextvars.bind_contextvars(
                                request_id=event.correlation_id or event.id, event_type=event.type, event_id=event.id)
                            try:
                                if handled_types is None or event.type in handled_types:
                                    await handler(event)
                                    log.info("event_handled", topic=topic, subscription=subscription)
                            finally:
                                structlog.contextvars.unbind_contextvars("request_id", "event_type", "event_id")
                            await receiver.complete_message(message)
                        except Exception:
                            log.exception("event_handler_failed", topic=topic, subscription=subscription)
                            await receiver.abandon_message(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Emulator may not be ready yet (it depends on SQL Server) — back off and retry.
            log.warning("consumer_connection_failed_retrying", topic=topic, subscription=subscription)
            await asyncio.sleep(5)
