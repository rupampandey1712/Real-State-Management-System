import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import jwt
import redis.asyncio as redis
from fastapi import Cookie, Depends, Query, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import otp, tokens
from app.config import settings
from app.models import User
from estate_common import auth
from estate_common.app import create_app, postgres_check, redis_check
from estate_common.auth import Admin
from estate_common.auth import User as CurrentUserDep
from estate_common.db import Database
from estate_common.errors import NotFound, Unauthorized

db = Database(settings.database_url)
store = redis.from_url(settings.redis_url)
Session = Annotated[AsyncSession, Depends(db.session)]

# Identity verifies its own tokens from its in-memory key set instead of calling its own JWKS endpoint.
_public_keys: dict[str, object] = {}


async def _refresh_public_keys() -> None:
    async with db.sessionmaker() as session:
        await tokens.ensure_active_key(session)
        keys = await tokens.published_keys(session)
    _public_keys.clear()
    _public_keys.update({k.kid: jwt.PyJWK(k.public_jwk).key for k in keys})


def _local_key(token: str):
    kid = jwt.get_unverified_header(token).get("kid")
    if kid not in _public_keys:
        raise jwt.InvalidTokenError("Unknown signing key.")
    return _public_keys[kid]


async def _seed_dev_users() -> None:
    async with db.sessionmaker() as session:
        for email, role in [(settings.dev_admin_email, "admin"), (settings.dev_agent_email, "agent")]:
            if not await session.scalar(select(User).where(User.email == email)):
                session.add(User(email=email, name=role.title(), role=role, agent_verified=True))
        await session.commit()


@asynccontextmanager
async def lifespan(_app):
    # Schema is managed by Alembic (`alembic upgrade head` runs before the server starts).
    await _refresh_public_keys()
    auth.set_key_resolver(_local_key)
    if settings.is_local:
        await _seed_dev_users()
    yield


app = create_app(settings, title="Identity Service", lifespan=lifespan,
                 readiness={"postgres": postgres_check(db), "redis": redis_check(store)})


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    role: str
    agent_verified: bool

    model_config = {"from_attributes": True}


class OtpRequest(BaseModel):
    email: EmailStr


class OtpVerify(BaseModel):
    email: EmailStr
    code: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


def _set_refresh_cookie(response: Response, raw: str) -> None:
    response.set_cookie(
        settings.refresh_cookie_name, raw, max_age=settings.refresh_token_ttl_s, httponly=True,
        secure=not settings.is_local, samesite="strict", path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(settings.refresh_cookie_name, path="/api/v1/auth")


async def _session_for(session: AsyncSession, user: User, response: Response, request: Request,
                       family_id: uuid.UUID | None = None) -> TokenOut:
    key = await tokens.ensure_active_key(session)
    raw, row = tokens.new_refresh_token(user.id, family_id, request.headers.get("user-agent"))
    session.add(row)
    await session.commit()
    access, ttl = tokens.issue_access_token(user, key)
    _set_refresh_cookie(response, raw)
    return TokenOut(access_token=access, expires_in=ttl, user=UserOut.model_validate(user))


# ─────────────────────────────── sign-in ───────────────────────────────
@app.post("/api/v1/auth/otp/request")
async def request_otp(body: OtpRequest) -> dict:
    email = body.email.lower()
    code = await otp.create_code(email)
    await otp.send_code_email(email, code)
    response = {"sent": True}
    if settings.is_local:
        response["dev_code"] = code  # local convenience only; also visible in Mailpit
    return response


@app.post("/api/v1/auth/otp/verify")
async def verify_otp(body: OtpVerify, session: Session, request: Request, response: Response) -> TokenOut:
    email = body.email.lower()
    if not await otp.verify_code(email, body.code.strip()):
        raise Unauthorized("Invalid or expired code.")
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, role="buyer")
        session.add(user)
        await session.commit()
        await session.refresh(user)
    if user.suspended_at:
        raise Unauthorized("This account is suspended.")
    return await _session_for(session, user, response, request)


@app.post("/api/v1/auth/refresh")
async def refresh(session: Session, request: Request, response: Response,
                  estate_refresh: Annotated[str | None, Cookie()] = None) -> TokenOut:
    if not estate_refresh:
        raise Unauthorized("Sign in to continue.")
    try:
        raw, row = await tokens.rotate_refresh_token(session, estate_refresh, request.headers.get("user-agent"))
    except tokens.RefreshRejected as exc:
        _clear_refresh_cookie(response)
        raise Unauthorized("Your session has ended. Sign in again.") from exc
    user = await session.get(User, row.user_id)
    if user is None or user.suspended_at:
        raise Unauthorized("This account is not available.")
    await session.commit()
    key = await tokens.ensure_active_key(session)
    access, ttl = tokens.issue_access_token(user, key)
    _set_refresh_cookie(response, raw)
    return TokenOut(access_token=access, expires_in=ttl, user=UserOut.model_validate(user))


@app.post("/api/v1/auth/logout", status_code=204)
async def logout(session: Session, request: Request, response: Response,
                 estate_refresh: Annotated[str | None, Cookie()] = None) -> None:
    """Ends this device's session: revokes the refresh-token family and denylists the current access token."""
    if estate_refresh:
        row = await session.scalar(select(tokens.RefreshToken).where(tokens.RefreshToken.token_hash == tokens.hash_token(estate_refresh)))
        if row:
            await tokens.revoke_family(session, row.family_id)
            await session.commit()
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        try:
            user = await auth.decode_token(header.split(" ", 1)[1])
            await store.set(f"jwt:deny:{user.jti}", 1, ex=max(user.expires_at - int(time.time()), 1))
        except Exception:
            pass  # already invalid — nothing to revoke
    _clear_refresh_cookie(response)


@app.post("/api/v1/auth/logout-all", status_code=204)
async def logout_all(current: CurrentUserDep, session: Session, response: Response) -> None:
    """Signs the user out everywhere: all refresh tokens revoked, all live access tokens cut off."""
    await tokens.revoke_all_for_user(session, uuid.UUID(current.id))
    await session.commit()
    await store.set(f"jwt:revoked_before:{current.id}", int(time.time()) + 1, ex=settings.access_token_ttl_s + 60)
    _clear_refresh_cookie(response)


@app.get("/api/v1/me")
async def me(current: CurrentUserDep, session: Session) -> UserOut:
    user = await session.get(User, uuid.UUID(current.id))
    if user is None:
        raise NotFound("User not found.")
    return UserOut.model_validate(user)


# ─────────────────────────────── admin ───────────────────────────────
class RoleUpdate(BaseModel):
    role: Literal["buyer", "agent", "admin"]
    agent_verified: bool = False


@app.get("/api/v1/admin/users")
async def list_users(_admin: Admin, session: Session, email: str | None = None,
                     limit: int = Query(50, ge=1, le=200)) -> list[UserOut]:
    """Newest first; `email` filters by substring. Used by the admin page to find users to verify."""
    stmt = select(User).order_by(User.created_at.desc()).limit(limit)
    if email:
        stmt = stmt.where(User.email.ilike(f"%{email.strip().lower()}%"))
    return [UserOut.model_validate(u) for u in await session.scalars(stmt)]


@app.post("/api/v1/admin/users/{user_id}/role")
async def set_role(user_id: uuid.UUID, body: RoleUpdate, _admin: Admin, session: Session) -> UserOut:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("User not found.")
    user.role, user.agent_verified = body.role, body.agent_verified
    await session.commit()
    # Old tokens carry the old role — cut them off so the change applies immediately.
    await store.set(f"jwt:revoked_before:{user_id}", int(time.time()) + 1, ex=settings.access_token_ttl_s + 60)
    return UserOut.model_validate(user)


@app.post("/api/v1/admin/keys/rotate")
async def rotate_keys(_admin: Admin, session: Session) -> dict:
    key = await tokens.rotate_key(session)
    await _refresh_public_keys()
    return {"kid": key.kid, "note": "Previous key stays in JWKS until its tokens expire."}


# ─────────────────────────────── discovery (JWKS) ───────────────────────────────
@app.get("/.well-known/openid-configuration")
async def openid_configuration() -> dict:
    return {
        "issuer": settings.jwt_issuer,
        "jwks_uri": f"{settings.identity_url}/.well-known/jwks.json",
        "id_token_signing_alg_values_supported": ["RS256"],
    }


@app.get("/.well-known/jwks.json")
async def jwks(session: Session, response: Response) -> dict:
    response.headers["Cache-Control"] = "public, max-age=300"
    return {"keys": [k.public_jwk for k in await tokens.published_keys(session)]}


# ─────────────────────────────── internal ───────────────────────────────
@app.get("/internal/users/{user_id}")
async def internal_get_user(user_id: uuid.UUID, session: Session) -> UserOut:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("User not found.")
    return UserOut.model_validate(user)


@app.get("/internal/users/by-email/{email}")
async def internal_get_user_by_email(email: str, session: Session) -> UserOut:
    user = await session.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        raise NotFound("User not found.")
    return UserOut.model_validate(user)
