import fakeredis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from estate_common.errors import install_error_handling
from estate_common.idempotency import IdempotencyMiddleware


def make_app():
    app = FastAPI()
    install_error_handling(app)
    app.state.created = 0
    app.add_middleware(IdempotencyMiddleware, client=fakeredis.FakeAsyncRedis(), service="test", paths=[r"/orders"])

    @app.post("/orders", status_code=201)
    async def create(payload: dict):
        app.state.created += 1
        return {"order": app.state.created, **payload}

    @app.post("/other")
    async def other():
        app.state.created += 1
        return {}

    return app


def test_replays_the_first_response():
    app = make_app()
    client = TestClient(app)
    first = client.post("/orders", json={"item": "a"}, headers={"Idempotency-Key": "k1"})
    second = client.post("/orders", json={"item": "a"}, headers={"Idempotency-Key": "k1"})
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json() == {"order": 1, "item": "a"}
    assert second.headers["Idempotent-Replayed"] == "true"
    assert app.state.created == 1


def test_same_key_different_body_is_rejected():
    client = TestClient(make_app())
    client.post("/orders", json={"item": "a"}, headers={"Idempotency-Key": "k2"})
    reused = client.post("/orders", json={"item": "b"}, headers={"Idempotency-Key": "k2"})
    assert reused.status_code == 422
    assert reused.json()["error"]["code"] == "idempotency_key_reused"


def test_no_key_or_other_paths_are_untouched():
    app = make_app()
    client = TestClient(app)
    client.post("/orders", json={"item": "a"})
    client.post("/orders", json={"item": "a"})
    client.post("/other", headers={"Idempotency-Key": "k3"})
    client.post("/other", headers={"Idempotency-Key": "k3"})
    assert app.state.created == 4
