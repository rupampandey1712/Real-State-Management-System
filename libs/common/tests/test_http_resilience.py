import httpx
import pytest

from estate_common.errors import DependencyUnavailable
from estate_common.http import CircuitBreaker, ResilientClient


def client_with(handler, **kwargs) -> ResilientClient:
    return ResilientClient("upstream", "http://upstream", transport=httpx.MockTransport(handler), backoff_s=0, **kwargs)


async def test_get_is_retried_on_transient_status():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) == 1 else 200, json={"ok": True})

    response = await client_with(handler).get("/x")
    assert response.status_code == 200 and len(calls) == 2


async def test_post_is_not_retried_unless_marked_idempotent():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("down")

    with pytest.raises(DependencyUnavailable):
        await client_with(handler).post("/x", json={})
    assert len(calls) == 1

    calls.clear()
    with pytest.raises(DependencyUnavailable):
        await client_with(handler, retries=2).post("/x", json={}, idempotent=True)
    assert len(calls) == 3


async def test_4xx_is_returned_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404)

    assert (await client_with(handler).get("/x")).status_code == 404
    assert len(calls) == 1


async def test_breaker_opens_and_fails_fast():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("down")

    client = client_with(handler, retries=0)
    client.breaker.failure_threshold = 3
    for _ in range(3):
        with pytest.raises(DependencyUnavailable):
            await client.get("/x")
    assert client.breaker.state == "open"
    with pytest.raises(DependencyUnavailable):
        await client.get("/x")
    assert len(calls) == 3  # the 4th call never reached the network


def test_breaker_half_open_allows_one_trial_then_closes():
    now = [0.0]
    breaker = CircuitBreaker("x", failure_threshold=2, reset_s=10, clock=lambda: now[0])
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == "open" and not breaker.allow()
    now[0] = 11
    assert breaker.state == "half_open"
    assert breaker.allow() and not breaker.allow()  # only one trial in flight
    breaker.record_success()
    assert breaker.state == "closed" and breaker.allow()


def test_breaker_reopens_when_trial_fails():
    now = [0.0]
    breaker = CircuitBreaker("x", failure_threshold=1, reset_s=10, clock=lambda: now[0])
    breaker.record_failure()
    now[0] = 11
    assert breaker.allow()
    breaker.record_failure()
    assert breaker.state == "open"
