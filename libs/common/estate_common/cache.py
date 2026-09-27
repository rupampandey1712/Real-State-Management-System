"""Two-level cache: L1 in-process (TTL, bounded) + L2 Redis (shared across replicas).

- get_or_load(): L1 → L2 → loader, with single-flight per key (no stampede on a cold key).
- invalidate(key): deletes L2, drops L1 here, and broadcasts over Redis pub/sub so other replicas drop L1.
- Versioned namespaces (for query-shaped keys like search results): bump_version() makes every
  existing entry unreachable at once — used when any listing event arrives.
- Redis failures degrade to "no cache" (the loader runs); they never fail the request.
Values must be JSON-serialisable.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as redis
import structlog
from cachetools import TTLCache

log = structlog.get_logger(__name__)


class TwoLevelCache:
    def __init__(self, client: redis.Redis, namespace: str, *, l1_ttl_s: float = 10, l2_ttl_s: int = 60, l1_max: int = 2048):
        self._redis = client
        self.namespace = namespace
        self._l1: TTLCache = TTLCache(maxsize=l1_max, ttl=l1_ttl_s)
        self._l2_ttl = l2_ttl_s
        self._locks: dict[str, asyncio.Lock] = {}
        self._channel = f"cacheinv:{namespace}"

    async def _version(self) -> int:
        value = await self._redis.get(f"cachever:{self.namespace}")
        return int(value or 0)

    async def _full_key(self, key: str, versioned: bool) -> str:
        return f"{self.namespace}:v{await self._version()}:{key}" if versioned else f"{self.namespace}:{key}"

    async def get_or_load(self, key: str, loader: Callable[[], Awaitable[Any]], *, versioned: bool = False) -> Any:
        try:
            full = await self._full_key(key, versioned)
        except redis.RedisError:
            log.warning("cache_unavailable_bypassing", namespace=self.namespace)
            return await loader()
        if full in self._l1:
            return self._l1[full]
        try:
            raw = await self._redis.get(f"cache:{full}")
            if raw is not None:
                value = json.loads(raw)
                self._l1[full] = value
                return value
        except redis.RedisError:
            pass
        lock = self._locks.setdefault(full, asyncio.Lock())
        try:
            async with lock:
                if full in self._l1:
                    return self._l1[full]
                value = await loader()
                if value is not None:
                    self._l1[full] = value
                    try:
                        await self._redis.set(f"cache:{full}", json.dumps(value, default=str), ex=self._l2_ttl)
                    except redis.RedisError:
                        pass
                return value
        finally:
            if not lock.locked():
                self._locks.pop(full, None)

    async def invalidate(self, key: str) -> None:
        full = f"{self.namespace}:{key}"
        self._l1.pop(full, None)
        try:
            await self._redis.delete(f"cache:{full}")
            await self._redis.publish(self._channel, full)
        except redis.RedisError:
            log.warning("cache_invalidate_failed", namespace=self.namespace, key=key)

    async def bump_version(self) -> None:
        self._l1.clear()
        try:
            await self._redis.incr(f"cachever:{self.namespace}")
            await self._redis.publish(self._channel, "*")
        except redis.RedisError:
            log.warning("cache_version_bump_failed", namespace=self.namespace)

    def _drop_local(self, message: str) -> None:
        if message == "*":
            self._l1.clear()
        else:
            self._l1.pop(message, None)

    async def listen_for_invalidations(self) -> None:
        """Background task: keep this replica's L1 in step with invalidations from other replicas."""
        while True:
            try:
                pubsub = self._redis.pubsub()
                await pubsub.subscribe(self._channel)
                async for message in pubsub.listen():
                    if message.get("type") == "message":
                        data = message["data"]
                        self._drop_local(data.decode() if isinstance(data, bytes) else data)
            except asyncio.CancelledError:
                raise
            except redis.RedisError:
                self._l1.clear()  # we may have missed invalidations
                await asyncio.sleep(5)
