"""Signing keys, access tokens (RS256 JWT) and refresh tokens (opaque, hashed, rotated)."""

import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import RefreshToken, SigningKey, User


# ── signing keys ──────────────────────────────────────────────────────────────
def generate_key() -> SigningKey:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = uuid.uuid4().hex
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    jwk = json.loads(RSAAlgorithm.to_jwk(private.public_key())) | {"kid": kid, "use": "sig", "alg": "RS256"}
    return SigningKey(kid=kid, private_pem=pem.decode(), public_jwk=jwk)


def key_grace() -> timedelta:
    """How long a retired key stays published: longest-lived token it signed, plus clock skew."""
    return timedelta(seconds=settings.access_token_ttl_s + 300)


async def active_key(session: AsyncSession) -> SigningKey | None:
    return await session.scalar(
        select(SigningKey).where(SigningKey.retired_at.is_(None)).order_by(SigningKey.created_at.desc()).limit(1)
    )


async def rotate_key(session: AsyncSession) -> SigningKey:
    await session.execute(update(SigningKey).where(SigningKey.retired_at.is_(None)).values(retired_at=datetime.now(UTC)))
    key = generate_key()
    session.add(key)
    await session.commit()
    return key


async def ensure_active_key(session: AsyncSession) -> SigningKey:
    key = await active_key(session)
    max_age = timedelta(days=settings.signing_key_rotation_days)
    if key is None or datetime.now(UTC) - key.created_at > max_age:
        key = await rotate_key(session)
    return key


async def published_keys(session: AsyncSession) -> list[SigningKey]:
    cutoff = datetime.now(UTC) - key_grace()
    return list(await session.scalars(
        select(SigningKey).where((SigningKey.retired_at.is_(None)) | (SigningKey.retired_at > cutoff))
    ))


# ── access tokens ─────────────────────────────────────────────────────────────
def issue_access_token(user: User, key: SigningKey) -> tuple[str, int]:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user.id),
        "role": user.role,
        "agent_verified": user.agent_verified,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_s)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, key.private_pem, algorithm="RS256", headers={"kid": key.kid}), settings.access_token_ttl_s


# ── refresh tokens ────────────────────────────────────────────────────────────
def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_refresh_token(user_id: uuid.UUID, family_id: uuid.UUID | None, user_agent: str | None) -> tuple[str, RefreshToken]:
    raw = secrets.token_urlsafe(32)
    row = RefreshToken(
        user_id=user_id, family_id=family_id or uuid.uuid4(), token_hash=hash_token(raw),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.refresh_token_ttl_s),
        user_agent=(user_agent or "")[:200] or None,
    )
    return raw, row


class RefreshRejected(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


async def rotate_refresh_token(session: AsyncSession, raw: str, user_agent: str | None) -> tuple[str, RefreshToken]:
    """Validates a presented refresh token and returns its replacement. Reuse revokes the family."""
    current = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
    now = datetime.now(UTC)
    if current is None:
        raise RefreshRejected("unknown")
    if current.revoked_at is not None:
        await revoke_family(session, current.family_id)
        await session.commit()
        raise RefreshRejected("reused")
    if current.expires_at <= now:
        raise RefreshRejected("expired")
    new_raw, replacement = new_refresh_token(current.user_id, current.family_id, user_agent)
    session.add(replacement)
    await session.flush()
    current.revoked_at, current.replaced_by = now, replacement.id
    return new_raw, replacement


async def revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(update(RefreshToken).where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
                          .values(revoked_at=datetime.now(UTC)))


async def revoke_all_for_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
                          .values(revoked_at=datetime.now(UTC)))
