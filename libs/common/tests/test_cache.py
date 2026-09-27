import asyncio

import fakeredis
import pytest
import redis.asyncio as redis

from estate_common.cache import TwoLevelCache


@pytest.fixture
def client():
    return fakeredis.FakeAsyncRedis()


async def test_loads_once_then_serves_from_l1_and_l2(client):
    calls = []

    async def loader():
        calls.append(1)
        return {"id": "L1", "price": 78}

    cache = TwoLevelCache(client, "listing")
    assert await cache.get_or_load("L1", loader) == {"id": "L1", "price": 78}
    assert await cache.get_or_load("L1", loader) == {"id": "L1", "price": 78}
    assert len(calls) == 1

    other_replica = TwoLevelCache(client, "listing")  # empty L1, shared L2
    assert await other_replica.get_or_load("L1", loader) == {"id": "L1", "price": 78}
    assert len(calls) == 1


async def test_single_flight_on_cold_key(client):
    calls = []

    async def slow_loader():
        calls.append(1)
        await asyncio.sleep(0.05)
        return [1, 2, 3]

    cache = TwoLevelCache(client, "search")
    results = await asyncio.gather(*[cache.get_or_load("q", slow_loader) for _ in range(10)])
    assert all(r == [1, 2, 3] for r in results)
    assert len(calls) == 1


async def test_invalidate_and_version_bump(client):
    value = {"n": 1}

    async def loader():
        return dict(value)

    cache = TwoLevelCache(client, "listing")
    await cache.get_or_load("L1", loader)
    value["n"] = 2
    await cache.invalidate("L1")
    assert await cache.get_or_load("L1", loader) == {"n": 2}

    search = TwoLevelCache(client, "search")
    await search.get_or_load("city=Pune", loader, versioned=True)
    value["n"] = 3
    await search.bump_version()
    assert await search.get_or_load("city=Pune", loader, versioned=True) == {"n": 3}


async def test_redis_outage_degrades_to_loader():
    class Broken(fakeredis.FakeAsyncRedis):
        async def get(self, *args, **kwargs):
            raise redis.ConnectionError("down")

    cache = TwoLevelCache(Broken(), "listing")

    async def loader():
        return {"fresh": True}

    assert await cache.get_or_load("L1", loader) == {"fresh": True}
