"""Resilient service-to-service HTTP: timeouts, retries with jittered backoff, and a circuit breaker.

- Retries only idempotent calls (GET/HEAD by default; pass idempotent=True for pure POSTs such as
  embeddings or query parsing). Never retries 4xx — those are the caller's problem.
- The breaker opens after N consecutive failures (transport errors or 502/503/504), fails fast for
  `reset_s`, then lets one trial call through (half-open). Callers get DependencyUnavailable (503).
"""

import asyncio
import random
import time

import httpx
import structlog

from estate_common.errors import DependencyUnavailable
from estate_common.settings import CommonSettings

log = structlog.get_logger(__name__)
TRANSIENT_STATUS = {502, 503, 504}


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 5, reset_s: float = 30.0, clock=time.monotonic):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_s = reset_s
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._trial_in_flight = False

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        return "half_open" if self._clock() - self._opened_at >= self.reset_s else "open"

    def allow(self) -> bool:
        state = self.state
        if state == "closed":
            return True
        if state == "half_open" and not self._trial_in_flight:
            self._trial_in_flight = True
            return True
        return False

    def record_success(self) -> None:
        if self._opened_at is not None:
            log.info("circuit_closed", dependency=self.name)
        self._failures, self._opened_at, self._trial_in_flight = 0, None, False

    def record_failure(self) -> None:
        self._failures += 1
        self._trial_in_flight = False
        if self._opened_at is not None or self._failures >= self.failure_threshold:
            if self.state != "open":
                log.error("circuit_opened", dependency=self.name, failures=self._failures)
            self._opened_at = self._clock()


class ResilientClient:
    def __init__(self, name: str, base_url: str, *, settings: CommonSettings | None = None,
                 timeout: float | None = None, retries: int | None = None, backoff_s: float = 0.2,
                 transport: httpx.AsyncBaseTransport | None = None):
        s = settings or CommonSettings()
        self.name = name
        self.retries = s.http_retries if retries is None else retries
        self.backoff_s = backoff_s
        self.breaker = CircuitBreaker(name, s.breaker_failure_threshold, s.breaker_reset_s)
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout or s.http_timeout_s, transport=transport)

    async def request(self, method: str, url: str, *, idempotent: bool | None = None, **kwargs) -> httpx.Response:
        safe = method.upper() in {"GET", "HEAD"} if idempotent is None else idempotent
        attempts = 1 + (self.retries if safe else 0)
        last: Exception | httpx.Response | None = None
        for attempt in range(attempts):
            if not self.breaker.allow():
                raise DependencyUnavailable(f"The {self.name} service is temporarily unavailable.")
            headers = dict(kwargs.pop("headers", None) or {})
            if request_id := structlog.contextvars.get_contextvars().get("request_id"):
                headers.setdefault("X-Request-Id", request_id)  # keep one id across service hops
            try:
                response = await self._http.request(method, url, headers=headers, **kwargs)
            except httpx.TransportError as exc:  # connect/read errors and timeouts
                self.breaker.record_failure()
                last = exc
            else:
                if response.status_code not in TRANSIENT_STATUS:
                    self.breaker.record_success()
                    return response
                self.breaker.record_failure()
                last = response
            if attempt < attempts - 1:
                await asyncio.sleep(self.backoff_s * 2**attempt * random.uniform(0.5, 1.5))
        log.warning("dependency_call_failed", dependency=self.name, url=url, attempts=attempts)
        if isinstance(last, httpx.Response):
            return last
        raise DependencyUnavailable(f"The {self.name} service is temporarily unavailable.") from last

    async def get(self, url: str, **kwargs) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def aclose(self) -> None:
        await self._http.aclose()
