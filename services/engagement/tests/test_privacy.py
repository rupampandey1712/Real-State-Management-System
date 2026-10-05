from datetime import UTC, datetime, timedelta

from app.privacy import SCRUBBED_MESSAGE, erase_user, purge_old_enquiries


class FakeContainer:
    """Just enough of the Cosmos ContainerProxy for app.privacy: items keyed by (partition, id)."""

    def __init__(self, partition_field: str, items: list[dict]):
        self.field = partition_field
        self.items = {(i[partition_field], i["id"]): i for i in items}

    def query_items(self, query: str, parameters: list[dict], partition_key: str | None = None):
        value = parameters[0]["value"]
        if "createdAt <" in query:
            matches = [i for i in self.items.values() if i["createdAt"] < value]
        else:
            field = query.split("WHERE c.")[1].split(" ")[0]
            matches = [i for i in self.items.values() if i.get(field) == value]

        async def iterate():
            for item in matches:
                yield item
        return iterate()

    async def delete_item(self, item: str, partition_key: str) -> None:
        del self.items[(partition_key, item)]

    async def replace_item(self, item: str, body: dict) -> None:
        self.items[(body[self.field], item)] = body


class FakeStore:
    def __init__(self, **containers: FakeContainer):
        self.containers = containers

    def __getitem__(self, name: str) -> FakeContainer:
        return self.containers[name]

    async def query(self, container: str, query: str, parameters: list[dict], partition_key: str) -> list[dict]:
        return [i async for i in self[container].query_items(query, parameters, partition_key)]


def make_store(enquiries: list[dict]) -> FakeStore:
    return FakeStore(**{
        "favourites": FakeContainer("userId", [{"id": "u1:l1", "userId": "u1"}, {"id": "u2:l1", "userId": "u2"}]),
        "saved-searches": FakeContainer("userId", [{"id": "s1", "userId": "u1"}]),
        "enquiries": FakeContainer("agentId", enquiries),
    })


def enquiry(id_: str, agent: str, buyer: str | None, created: datetime | None = None) -> dict:
    return {"id": id_, "agentId": agent, "buyerId": buyer, "name": "Priya", "email": "priya@example.com",
            "phone": "+91 98765 43210", "message": "Is parking included?", "listingId": "l1",
            "createdAt": (created or datetime.now(UTC)).isoformat()}


async def test_erase_buyer_scrubs_their_enquiries_and_deletes_their_lists():
    store = make_store([enquiry("e1", "agent", "u1"), enquiry("e2", "agent", "u2")])
    counts = await erase_user(store, "u1")
    assert counts == {"favourites": 1, "saved_searches": 1, "enquiries_scrubbed": 1, "enquiries_deleted": 0}
    scrubbed = store["enquiries"].items[("agent", "e1")]
    assert scrubbed["email"] is None and scrubbed["phone"] is None and scrubbed["message"] == SCRUBBED_MESSAGE
    assert scrubbed["listingId"] == "l1"  # the agent still sees that an enquiry happened
    assert store["enquiries"].items[("agent", "e2")]["email"] == "priya@example.com"  # other buyers untouched
    assert list(store["favourites"].items) == [("u2", "u2:l1")]


async def test_erase_agent_deletes_enquiries_they_received():
    store = make_store([enquiry("e1", "u1", "buyer"), enquiry("e2", "other", "buyer")])
    counts = await erase_user(store, "u1")
    assert counts["enquiries_deleted"] == 1
    assert list(store["enquiries"].items) == [("other", "e2")]


async def test_erasure_is_idempotent():
    store = make_store([enquiry("e1", "agent", "u1")])
    await erase_user(store, "u1")
    again = await erase_user(store, "u1")
    assert again == {"favourites": 0, "saved_searches": 0, "enquiries_scrubbed": 0, "enquiries_deleted": 0}


async def test_enquiries_older_than_two_years_are_purged():
    now = datetime.now(UTC)
    store = make_store([enquiry("old", "a", None, now - timedelta(days=731)), enquiry("new", "a", None, now - timedelta(days=700))])
    assert await purge_old_enquiries(store, now) == 1
    assert list(store["enquiries"].items) == [("a", "new")]
