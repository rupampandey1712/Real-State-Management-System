"""JWT verification for every service (ADR-0015).

Tokens are RS256, signed by the identity service. Public keys come from its JWKS endpoint (cached,
refetched when an unknown `kid` appears, so key rotation needs no redeploy). After signature and
claim checks, the revocation list in Redis is consulted:
  jwt:deny:{jti}            — single token revoked (logout), TTL = remaining token life
  jwt:revoked_before:{sub}  — every token for a user issued before this unix time (logout-all, suspension)
If Redis is unreachable the check fails open (tokens live 15 minutes) and a warning is logged.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import jwt
import redis.asyncio as redis
import structlog
from fastapi import Depends, Header

from estate_common.errors import DependencyUnavailable, Forbidden, Unauthorized
from estate_common.settings import CommonSettings

log = structlog.get_logger(__name__)
_settings = CommonSettings()


@dataclass(frozen=True)
class CurrentUser:
    id: str
    role: str  # buyer | agent | admin
    agent_verified: bool = False
    jti: str = ""
    expires_at: int = 0

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(_settings.jwks_url, cache_keys=True, lifespan=300, timeout=5)


def _jwks_key(token: str) -> Any:
    return _jwks_client().get_signing_key_from_jwt(token).key


# Overridable: the identity service resolves keys locally; tests inject a static key.
KeyResolver = Callable[[str], Any]
_key_resolver: KeyResolver = _jwks_key


def set_key_resolver(resolver: KeyResolver) -> None:
    global _key_resolver
    _key_resolver = resolver


@lru_cache
def revocation_store() -> redis.Redis | None:
    return redis.from_url(_settings.redis_url) if _settings.redis_url else None


async def is_revoked(jti: str, sub: str, iat: int) -> bool:
    store = revocation_store()
    if store is None:
        return False
    try:
        if jti and await store.exists(f"jwt:deny:{jti}"):
            return True
        before = await store.get(f"jwt:revoked_before:{sub}")
        return before is not None and iat < int(before)
    except redis.RedisError:
        log.warning("revocation_check_unavailable_failing_open")
        return False


async def decode_token(token: str) -> CurrentUser:
    try:
        key = await asyncio.to_thread(_key_resolver, token)
        claims = jwt.decode(
            token, key, algorithms=["RS256"], audience=_settings.jwt_audience, issuer=_settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "jti"]}, leeway=30,
        )
    except jwt.PyJWKClientConnectionError as exc:
        raise DependencyUnavailable("Sign-in keys are temporarily unavailable.") from exc
    except jwt.PyJWTError as exc:
        raise Unauthorized("Your session has expired. Sign in again.") from exc
    if await is_revoked(claims["jti"], claims["sub"], int(claims["iat"])):
        raise Unauthorized("Your session has ended. Sign in again.")
    return CurrentUser(
        id=claims["sub"], role=claims.get("role", "buyer"), agent_verified=claims.get("agent_verified", False),
        jti=claims["jti"], expires_at=int(claims["exp"]),
    )


async def optional_user(authorization: Annotated[str | None, Header()] = None) -> CurrentUser | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return await decode_token(authorization.split(" ", 1)[1])


async def require_user(user: Annotated[CurrentUser | None, Depends(optional_user)]) -> CurrentUser:
    if user is None:
        raise Unauthorized("Sign in required.")
    return user


def require_role(*roles: str):
    async def dependency(user: Annotated[CurrentUser, Depends(require_user)]) -> CurrentUser:
        if user.role not in roles:
            raise Forbidden("You don't have permission to do this.")
        return user

    return dependency


OptionalUser = Annotated[CurrentUser | None, Depends(optional_user)]
User = Annotated[CurrentUser, Depends(require_user)]
Agent = Annotated[CurrentUser, Depends(require_role("agent", "admin"))]
Admin = Annotated[CurrentUser, Depends(require_role("admin"))]
