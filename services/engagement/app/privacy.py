"""Erasure and retention for engagement data (FR-6.4, NFR-10, DPDP Act 2023).

- identity.user_deleted → the person's favourites and saved searches are deleted; enquiries they sent keep
  only the listing and date (contact details and message are scrubbed); if they were an agent, the enquiries
  they received are deleted (those hold other people's contact details).
- Enquiries older than `enquiry_retention_days` (2 years) are deleted.

Every function is idempotent: running it twice leaves the same result.
"""

from datetime import UTC, datetime, timedelta

from app.config import settings
from app.store import Store

SCRUBBED_NAME = "Deleted account"
SCRUBBED_MESSAGE = "[Removed at the sender's request]"


def scrub_enquiry(enquiry: dict) -> dict:
    return enquiry | {"name": SCRUBBED_NAME, "email": None, "phone": None, "message": SCRUBBED_MESSAGE,
                      "buyerId": None, "erasedAt": datetime.now(UTC).isoformat()}


async def _delete_all(store: Store, container: str, partition_key: str) -> int:
    items = await store.query(container, "SELECT c.id FROM c WHERE c.userId = @u",
                              [{"name": "@u", "value": partition_key}], partition_key=partition_key)
    for item in items:
        await store[container].delete_item(item=item["id"], partition_key=partition_key)
    return len(items)


async def erase_user(store: Store, user_id: str) -> dict[str, int]:
    counts = {
        "favourites": await _delete_all(store, "favourites", user_id),
        "saved_searches": await _delete_all(store, "saved-searches", user_id),
    }
    sent = [e async for e in store["enquiries"].query_items(
        query="SELECT * FROM c WHERE c.buyerId = @u", parameters=[{"name": "@u", "value": user_id}])]
    for enquiry in sent:
        await store["enquiries"].replace_item(item=enquiry["id"], body=scrub_enquiry(enquiry))
    received = await store.query("enquiries", "SELECT c.id FROM c WHERE c.agentId = @a",
                                 [{"name": "@a", "value": user_id}], partition_key=user_id)
    for enquiry in received:
        await store["enquiries"].delete_item(item=enquiry["id"], partition_key=user_id)
    counts |= {"enquiries_scrubbed": len(sent), "enquiries_deleted": len(received)}
    return counts


async def purge_old_enquiries(store: Store, now: datetime | None = None) -> int:
    cutoff = ((now or datetime.now(UTC)) - timedelta(days=settings.enquiry_retention_days)).isoformat()
    old = [e async for e in store["enquiries"].query_items(
        query="SELECT c.id, c.agentId FROM c WHERE c.createdAt < @cutoff",
        parameters=[{"name": "@cutoff", "value": cutoff}])]
    for enquiry in old:
        await store["enquiries"].delete_item(item=enquiry["id"], partition_key=enquiry["agentId"])
    return len(old)
