import fakeredis
import redis.asyncio as redis

from estate_common.flags import FeatureFlags


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_defaults_apply_until_overridden():
    client = fakeredis.FakeAsyncRedis()
    flags = FeatureFlags(client, {"ai_describe": True, "listing_qa": False})
    assert await flags.is_enabled("ai_describe") is True
    assert await flags.is_enabled("listing_qa") is False
    await flags.set("ai_describe", False)
    assert await flags.is_enabled("ai_describe") is False
    await flags.reset("ai_describe")
    assert await flags.is_enabled("ai_describe") is True


async def test_other_replicas_see_changes_after_cache_ttl():
    client, clock = fakeredis.FakeAsyncRedis(), Clock()
    admin = FeatureFlags(client, {"nl_search": True})
    replica = FeatureFlags(client, {"nl_search": True}, ttl_s=5, clock=clock)
    assert await replica.is_enabled("nl_search") is True
    await admin.set("nl_search", False)
    assert await replica.is_enabled("nl_search") is True  # still cached
    clock.now = 6
    assert await replica.is_enabled("nl_search") is False


async def test_redis_down_falls_back_to_config():
    class Broken:
        async def hgetall(self, _key):
            raise redis.ConnectionError("down")

    flags = FeatureFlags(Broken(), {"ai_describe": True})  # type: ignore[arg-type]
    assert await flags.is_enabled("ai_describe") is True


async def test_snapshot_lists_every_known_flag():
    flags = FeatureFlags(fakeredis.FakeAsyncRedis(), {"nl_search": True})
    snapshot = await flags.snapshot()
    assert set(snapshot) == {"nl_search", "ai_describe", "ai_improve", "listing_qa"}
    assert snapshot["nl_search"] == {"enabled": True, "overridden": False, "default": True,
                                     "description": snapshot["nl_search"]["description"]}
