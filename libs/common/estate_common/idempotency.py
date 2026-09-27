"""Idempotency keys for unsafe POSTs (Stripe-style).

A client sends `Idempotency-Key: <uuid>`. The first request claims the key in Redis and its response
(status < 500) is stored for 24 h; a repeat with the same key and the same body replays the stored
response with `Idempotent-Replayed: true`. Same key + different body → 422. A repeat while the first
is still running → 409. 5xx responses release the key so the client can retry.
Keys are scoped per caller (Authorization header or client IP) and per service.
If Redis is down the middleware steps aside (fail open) — duplicates are then possible, and logged.
"""

import base64
import hashlib
import json
import re

import redis.asyncio as redis
import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from estate_common.errors import envelope

log = structlog.get_logger(__name__)
HEADER = "Idempotency-Key"


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, client: redis.Redis, service: str, paths: list[str], ttl_s: int = 86_400):
        super().__init__(app)
        self._redis = client
        self._service = service
        self._paths = [re.compile(p) for p in paths]
        self._ttl = ttl_s

    def _applies(self, request: Request) -> bool:
        return request.method == "POST" and any(p.fullmatch(request.url.path) for p in self._paths)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        key = request.headers.get(HEADER)
        if not key or not self._applies(request):
            return await call_next(request)
        request_id = getattr(request.state, "request_id", "")
        if len(key) > 100:
            return envelope(request_id, 422, "validation_error", "Idempotency-Key must be at most 100 characters.")

        body = await request.body()
        fingerprint = hashlib.sha256(request.method.encode() + request.url.path.encode() + body).hexdigest()
        caller = request.headers.get("authorization") or (request.client.host if request.client else "anon")
        scope = hashlib.sha256(caller.encode()).hexdigest()[:16]
        redis_key = f"idem:{self._service}:{scope}:{key}"

        try:
            claimed = await self._redis.set(redis_key, json.dumps({"state": "processing", "fp": fingerprint}), nx=True, ex=self._ttl)
            if not claimed:
                existing = json.loads(await self._redis.get(redis_key) or "{}")
                if existing.get("fp") != fingerprint:
                    return envelope(request_id, 422, "idempotency_key_reused",
                                    "This Idempotency-Key was already used for a different request.")
                if existing.get("state") == "processing":
                    return envelope(request_id, 409, "request_in_progress", "The original request is still being processed.")
                return Response(
                    content=base64.b64decode(existing["body"]), status_code=existing["status"],
                    media_type=existing.get("content_type"), headers={"Idempotent-Replayed": "true"},
                )
        except redis.RedisError:
            log.warning("idempotency_store_unavailable_passing_through", path=request.url.path)
            return await call_next(request)

        response = await call_next(request)
        content = b"".join([chunk async for chunk in response.body_iterator])
        try:
            if response.status_code < 500:
                await self._redis.set(redis_key, json.dumps({
                    "state": "done", "fp": fingerprint, "status": response.status_code,
                    "body": base64.b64encode(content).decode(), "content_type": response.headers.get("content-type"),
                }), ex=self._ttl)
            else:
                await self._redis.delete(redis_key)
        except redis.RedisError:
            log.warning("idempotency_store_write_failed", path=request.url.path)
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return Response(content=content, status_code=response.status_code, headers=headers)
