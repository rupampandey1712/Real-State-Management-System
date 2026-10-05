import time

import fakeredis
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import signin
from app.config import settings

CLIENT_ID = "test-client.apps.googleusercontent.com"


@pytest.fixture
def fake_redis(monkeypatch):
    client = fakeredis.FakeAsyncRedis()
    monkeypatch.setattr(signin, "_redis", client)
    return client


async def test_magic_link_works_once(fake_redis):
    token = await signin.create_magic_token("priya@example.com")
    assert signin.magic_link(token).endswith(f"/login/magic#token={token}")  # fragment: never sent to servers
    assert await signin.consume_magic_token(token) == "priya@example.com"
    assert await signin.consume_magic_token(token) is None


async def test_magic_token_is_stored_hashed(fake_redis):
    token = await signin.create_magic_token("priya@example.com")
    keys = [k.decode() for k in await fake_redis.keys("*")]
    assert keys and all(token not in k for k in keys)


async def test_unknown_or_malformed_magic_token_is_rejected(fake_redis):
    assert await signin.consume_magic_token("x" * 43) is None
    assert await signin.consume_magic_token("short") is None


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", CLIENT_ID)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def make(**overrides) -> str:
        now = int(time.time())
        claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "1234", "email": "Rahul@Example.com",
                  "email_verified": True, "name": "Rahul", "iat": now, "exp": now + 600} | overrides
        return jwt.encode(claims, key, algorithm="RS256")

    return make, (lambda _token: key.public_key())


def test_valid_google_token_gives_lowercased_email(google):
    make, resolver = google
    assert signin.verify_google_id_token(make(), resolver) == ("rahul@example.com", "Rahul")


@pytest.mark.parametrize("overrides", [
    {"aud": "someone-else"},
    {"iss": "https://evil.example.com"},
    {"email_verified": False},
    {"exp": int(time.time()) - 3600},
])
def test_bad_google_tokens_are_rejected(google, overrides):
    make, resolver = google
    with pytest.raises(signin.GoogleTokenInvalid):
        signin.verify_google_id_token(make(**overrides), resolver)


def test_google_disabled_without_client_id(google, monkeypatch):
    make, resolver = google
    monkeypatch.setattr(settings, "google_client_id", "")
    with pytest.raises(signin.GoogleTokenInvalid):
        signin.verify_google_id_token(make(), resolver)
