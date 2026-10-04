"""Cosmos DB containers owned by the engagement service (ADR-0012).

| container      | partition key | why                                               |
|----------------|---------------|---------------------------------------------------|
| enquiries      | /agentId      | the hot query is "all enquiries for this agent"   |
| favourites     | /userId       | always read per user                              |
| saved-searches | /userId       | always read per user                              |
| product-events | /day          | success-metric rollups read whole days; TTL 90 d  |
"""

from azure.cosmos import PartitionKey
from azure.cosmos.aio import ContainerProxy, CosmosClient

from app.config import settings

CONTAINERS = {"enquiries": "/agentId", "favourites": "/userId", "saved-searches": "/userId", "product-events": "/day"}
TTL_S = {"product-events": 90 * 86_400}  # success metrics are read over 60 days (requirements §9)


class Store:
    def __init__(self) -> None:
        self.client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key, enable_endpoint_discovery=False)
        self.containers: dict[str, ContainerProxy] = {}

    async def init(self) -> None:
        database = await self.client.create_database_if_not_exists(settings.cosmos_database)
        for name, pk in CONTAINERS.items():
            self.containers[name] = await database.create_container_if_not_exists(
                id=name, partition_key=PartitionKey(path=pk), default_ttl=TTL_S.get(name))

    def __getitem__(self, name: str) -> ContainerProxy:
        return self.containers[name]

    async def query(self, container: str, query: str, parameters: list[dict], partition_key: str) -> list[dict]:
        items = self[container].query_items(query=query, parameters=parameters, partition_key=partition_key)
        return [item async for item in items]

    async def close(self) -> None:
        await self.client.close()


store = Store()
