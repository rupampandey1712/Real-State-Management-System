import time
import uuid

import fakeredis
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from estate_common import auth
from estate_common.errors import Unauthorized

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(key=KEY, **overrides) -> str:
    now = int(time.time())
    claims = {"sub": "u1", "role": "agent", "agent_verified": True, "iss": "estateai-identity", "aud": "estateai",
              "iat": now, "exp": now + 300, "jti": uuid.uuid4().hex} | overrides
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    store = fakeredis.FakeAsyncRedis()
    monkeypatch.setattr(auth, "revocation_store", lambda: store)
    auth.set_key_resolver(lambda _token: KEY.public_key())
    return store


async def test_valid_token_decodes():
    user = await auth.decode_token(token())
    assert (user.id, user.role, user.agent_verified) == ("u1", "agent", True)


@pytest.mark.parametrize("bad", [
    lambda: token(key=OTHER_KEY),                   # wrong signature
    lambda: token(exp=int(time.time()) - 120),      # expired beyond leeway
    lambda: token(aud="someone-else"),              # wrong audience
    lambda: token(iss="attacker"),                  # wrong issuer
    lambda: jwt.encode({"sub": "u1"}, "secret", algorithm="HS256"),  # algorithm confusion
])
async def test_invalid_tokens_are_rejected(bad):
    with pytest.raises(Unauthorized):
        await auth.decode_token(bad())


async def test_denylisted_jti_is_rejected(setup):
    t = token(jti="revoked")
    await setup.set("jwt:deny:revoked", 1)
    with pytest.raises(Unauthorized):
        await auth.decode_token(t)


async def test_revoked_before_cuts_off_older_tokens(setup):
    old = token(iat=int(time.time()) - 60)
    await setup.set("jwt:revoked_before:u1", int(time.time()) - 10)
    with pytest.raises(Unauthorized):
        await auth.decode_token(old)
    assert (await auth.decode_token(token())).id == "u1"
