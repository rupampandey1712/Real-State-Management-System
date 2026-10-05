"""Runtime feature flags (FR-7.4). Admins toggle them from the AI dashboard without a redeploy.

Storage: one Redis hash, `feature_flags` (field = flag name, value "1"/"0"). Each service passes its own
config defaults, which apply until an admin sets a value, and again whenever Redis is unreachable (fail
to config, never to "on"). Reads are cached per replica for `ttl_s` seconds, so a toggle reaches every
replica within a few seconds without a Redis call per request. Azure: the same Azure Managed Redis
(App Configuration is the alternative if flags ever need targeting or history).
"""

import time

import redis.asyncio as redis
import structlog

log = structlog.get_logger(__name__)
FLAGS_KEY = "feature_flags"

# Every flag the platform knows, with a description for the admin page. Owners read them; the ai
# service's admin API writes them.
KNOWN_FLAGS: dict[str, str] = {
    "nl_search": "Natural-language search (search service). Off: the search box runs a keyword search.",
    "ai_describe": "Description generator for agents.",
    "ai_improve": "\"Improve my text\" rewrite for agents.",
    "listing_qa": "Listing Q&A assistant on listing pages.",
}


class FeatureFlags:
    def __init__(self, client: redis.Redis, defaults: dict[str, bool], *, ttl_s: float = 5.0, clock=time.monotonic):
        self._redis = client
        self._defaults = defaults
        self._ttl = ttl_s
        self._clock = clock
        self._cached: dict[str, bool] = {}
        self._loaded_at = float("-inf")

    async def _overrides(self) -> dict[str, bool]:
        if self._clock() - self._loaded_at < self._ttl:
            return self._cached
        try:
            raw = await self._redis.hgetall(FLAGS_KEY)
            self._cached = {k.decode() if isinstance(k, bytes) else k: (v in (b"1", "1")) for k, v in raw.items()}
        except redis.RedisError:
            log.warning("feature_flags_unavailable_using_config_defaults")
            self._cached = {}
        self._loaded_at = self._clock()
        return self._cached

    async def is_enabled(self, name: str) -> bool:
        return (await self._overrides()).get(name, self._defaults.get(name, False))

    async def snapshot(self) -> dict[str, dict]:
        overrides = await self._overrides()
        return {
            name: {"enabled": overrides.get(name, self._defaults.get(name, False)), "overridden": name in overrides,
                   "default": self._defaults.get(name, False), "description": description}
            for name, description in KNOWN_FLAGS.items()
        }

    async def set(self, name: str, enabled: bool) -> None:
        if name not in KNOWN_FLAGS:
            raise KeyError(name)
        await self._redis.hset(FLAGS_KEY, name, "1" if enabled else "0")
        self._loaded_at = float("-inf")  # this replica sees the change at once

    async def reset(self, name: str) -> None:
        await self._redis.hdel(FLAGS_KEY, name)
        self._loaded_at = float("-inf")
