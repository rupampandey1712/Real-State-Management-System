import time
import uuid
from datetime import UTC, datetime, timedelta

import fakeredis
import jwt
import pytest

from app import tokens
from app.models import RefreshToken, User
from estate_common import auth
from estate_common.errors import Unauthorized


def make_user(role="agent") -> User:
    return User(id=uuid.uuid4(), email="a@b.c", role=role, agent_verified=True)


def test_key_publishes_rs256_jwk_without_private_parts():
    key = tokens.generate_key()
    jwk = key.public_jwk
    assert jwk["kty"] == "RSA" and jwk["alg"] == "RS256" and jwk["kid"] == key.kid
    assert "d" not in jwk and "p" not in jwk  # no private components in JWKS
    assert "BEGIN PRIVATE KEY" in key.private_pem


async def test_access_token_round_trips_through_shared_verifier(monkeypatch):
    key = tokens.generate_key()
    auth.set_key_resolver(lambda _t: jwt.PyJWK(key.public_jwk).key)
    monkeypatch.setattr(auth, "revocation_store", lambda: fakeredis.FakeAsyncRedis())
    user = make_user()
    token, ttl = tokens.issue_access_token(user, key)
    assert jwt.get_unverified_header(token)["kid"] == key.kid
    current = await auth.decode_token(token)
    assert (current.id, current.role, current.agent_verified) == (str(user.id), "agent", True)
    assert 0 < current.expires_at - time.time() <= ttl


async def test_token_signed_by_unknown_key_is_rejected(monkeypatch):
    trusted, rogue = tokens.generate_key(), tokens.generate_key()
    auth.set_key_resolver(lambda _t: jwt.PyJWK(trusted.public_jwk).key)
    monkeypatch.setattr(auth, "revocation_store", lambda: None)
    token, _ = tokens.issue_access_token(make_user(), rogue)
    with pytest.raises(Unauthorized):
        await auth.decode_token(token)


def test_refresh_tokens_are_random_and_stored_hashed():
    raw1, row1 = tokens.new_refresh_token(uuid.uuid4(), None, "ua")
    raw2, _ = tokens.new_refresh_token(uuid.uuid4(), None, "ua")
    assert raw1 != raw2 and len(raw1) >= 40
    assert row1.token_hash == tokens.hash_token(raw1) and raw1 not in row1.token_hash


class FakeSession:
    """Just enough of AsyncSession for rotate_refresh_token."""

    def __init__(self, existing: RefreshToken | None):
        self.existing = existing
        self.added: list = []
        self.revoked_families: list = []
        self.commits = 0

    async def scalar(self, _stmt):
        return self.existing

    def add(self, obj):
        obj.id = obj.id or uuid.uuid4()
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1


def stored(raw: str, **overrides) -> RefreshToken:
    return RefreshToken(id=uuid.uuid4(), user_id=uuid.uuid4(), family_id=uuid.uuid4(), token_hash=tokens.hash_token(raw),
                        expires_at=datetime.now(UTC) + timedelta(days=1), revoked_at=None, **overrides)


async def test_rotation_issues_replacement_in_same_family():
    current = stored("raw")
    session = FakeSession(current)
    new_raw, replacement = await tokens.rotate_refresh_token(session, "raw", "ua")
    assert new_raw != "raw"
    assert replacement.family_id == current.family_id
    assert current.revoked_at is not None and current.replaced_by == replacement.id


async def test_reuse_of_rotated_token_revokes_whole_family(monkeypatch):
    current = stored("raw")
    current.revoked_at = datetime.now(UTC)  # already rotated → presenting it again means it was stolen
    session = FakeSession(current)
    revoked = []

    async def fake_revoke(_session, family_id):
        revoked.append(family_id)

    monkeypatch.setattr(tokens, "revoke_family", fake_revoke)
    with pytest.raises(tokens.RefreshRejected) as exc:
        await tokens.rotate_refresh_token(session, "raw", "ua")
    assert exc.value.reason == "reused"
    assert revoked == [current.family_id] and session.commits == 1


async def test_expired_and_unknown_tokens_are_rejected():
    expired = stored("raw")
    expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(tokens.RefreshRejected, match="expired"):
        await tokens.rotate_refresh_token(FakeSession(expired), "raw", "ua")
    with pytest.raises(tokens.RefreshRejected, match="unknown"):
        await tokens.rotate_refresh_token(FakeSession(None), "raw", "ua")
