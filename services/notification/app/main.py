"""Notification worker: consumes engagement events and emails agents.
Local: SMTP → Mailpit (http://localhost:8025). Azure: Azure Communication Services Email."""

import asyncio
from email.message import EmailMessage

import aiosmtplib
import structlog

from estate_common import events
from estate_common.events import Event
from estate_common.http import ResilientClient
from estate_common.logging import configure_logging
from estate_common.messaging import consume_forever
from estate_common.settings import CommonSettings


class NotificationSettings(CommonSettings):
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    email_from: str = "no-reply@estateai.local"
    web_base_url: str = "http://localhost:3000"


settings = NotificationSettings(service_name="notification")
log = structlog.get_logger(__name__)
identity = ResilientClient("identity", settings.identity_url, settings=settings)
engagement = ResilientClient("engagement", settings.engagement_url, settings=settings)


async def on_enquiry_created(event: Event) -> None:
    data = event.data
    # Failures raise, so the message is abandoned: Service Bus retries it, then dead-letters it.
    agent = (await identity.get(f"/internal/users/{data['agent_id']}")).raise_for_status().json()
    enquiry = (await engagement.get(f"/internal/enquiries/{data['agent_id']}/{data['enquiry_id']}")).raise_for_status().json()

    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = agent["email"]
    message["Reply-To"] = enquiry["email"]
    message["Subject"] = f"New enquiry: {enquiry['listingTitle']}"
    message.set_content(
        f"{enquiry['name']} sent an enquiry about \"{enquiry['listingTitle']}\".\n\n"
        f"Message:\n{enquiry['message']}\n\n"
        f"Email: {enquiry['email']}\nPhone: {enquiry.get('phone') or '—'}\n\n"
        f"View listing: {settings.web_base_url}/listings/{enquiry['listingId']}\n"
    )
    await aiosmtplib.send(message, hostname=settings.smtp_host, port=settings.smtp_port)
    log.info("enquiry_email_sent", enquiry_id=data["enquiry_id"])  # no PII in logs


async def main() -> None:
    configure_logging(settings.service_name, settings.log_level)
    await consume_forever(settings.servicebus_connection, events.ENGAGEMENT_EVENTS, "notification", on_enquiry_created,
                          handled_types={events.ENQUIRY_CREATED})


if __name__ == "__main__":
    asyncio.run(main())
