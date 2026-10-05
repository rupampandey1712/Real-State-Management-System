import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import jwt
import redis.asyncio as redis
import structlog
from fastapi import Cookie, Depends, Query, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import otp, signin, tokens
from app.config import settings
from app.models import AdminAction, User
from estate_common import auth, events
from estate_common.app import create_app, postgres_check, redis_check
from estate_common.auth import Admin
from estate_common.auth import User as CurrentUserDep
from estate_common.db import Database
from estate_common.errors import Conflict, NotFound, Unauthorized, ValidationFailed
from estate_common.outbox import OutboxRelay, add_event

log = structlog.get_logger(__name__)
db = Database(settings.database_url)
store = redis.from_url(settings.redis_url)
relay = OutboxRelay(db, settings.servicebus_connection)
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


async def purge_deleted_accounts() -> int:
    """NFR-10: accounts deleted more than `account_purge_days` ago are removed for good (refresh tokens and
    audit rows cascade). Personal fields were already scrubbed at deletion time."""
    cutoff = datetime.now(UTC) - timedelta(days=settings.account_purge_days)
    async with db.sessionmaker() as session:
        result = await session.execute(delete(User).where(User.deleted_at.is_not(None), User.deleted_at < cutoff))
        await session.commit()
    return result.rowcount or 0  # type: ignore[attr-defined]


async def _purge_forever() -> None:
    while True:
        try:
            if purged := await purge_deleted_accounts():
                log.info("deleted_accounts_purged", count=purged)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("account_purge_failed")
        await asyncio.sleep(settings.purge_interval_s)


@asynccontextmanager
async def lifespan(_app):
    # Schema is managed by Alembic (`alembic upgrade head` runs before the server starts).
    await _refresh_public_keys()
    auth.set_key_resolver(_local_key)
    if settings.is_local:
        await _seed_dev_users()
    tasks = [asyncio.create_task(relay.run_forever()), asyncio.create_task(_purge_forever())]
    yield
    for task in tasks:
        task.cancel()


app = create_app(settings, title="Identity Service", lifespan=lifespan,
                 readiness={"postgres": postgres_check(db), "redis": redis_check(store)})


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    role: str
    agent_verified: bool
    agent_requested_at: datetime | None = None

    model_config = {"from_attributes": True}


class AdminUserOut(UserOut):
    phone: str | None
    agency_name: str | None
    rera_agent_id: str | None
    suspended_at: datetime | None
    created_at: datetime


class OtpRequest(BaseModel):
    email: EmailStr


class OtpVerify(BaseModel):
    email: EmailStr
    code: str


class MagicVerify(BaseModel):
    token: str = Field(min_length=20, max_length=100)


class GoogleSignIn(BaseModel):
    credential: str = Field(min_length=20, max_length=4096)


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
    access, ttl = tokens.issue_access_token(user, key, await _revoked_before(user.id))
    _set_refresh_cookie(response, raw)
    return TokenOut(access_token=access, expires_in=ttl, user=UserOut.model_validate(user))


async def _revoked_before(user_id: uuid.UUID) -> int | None:
    try:
        value = await store.get(f"jwt:revoked_before:{user_id}")
    except redis.RedisError:
        return None
    return int(value) if value else None


async def _user_for_email(session: AsyncSession, email: str, name: str | None = None) -> User:
    """Finds or creates (as a buyer) the account for a verified email address."""
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, role="buyer", name=name[:120] if name else None)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    if user.suspended_at:
        raise Unauthorized("This account is suspended.")
    return user


async def _cut_off_sessions(user_id: uuid.UUID) -> None:
    """Every access token issued before now stops working at once (role change, suspension, deletion)."""
    await store.set(f"jwt:revoked_before:{user_id}", int(time.time()) + 1, ex=settings.access_token_ttl_s + 60)


# ─────────────────────────────── sign-in (FR-6.1) ───────────────────────────────
@app.get("/api/v1/auth/providers")
async def sign_in_providers() -> dict:
    """Which sign-in methods the SPA should offer. The Google client id is public by design."""
    return {"email_code": True, "magic_link": True, "google_client_id": settings.google_client_id or None}


@app.post("/api/v1/auth/otp/request")
async def request_otp(body: OtpRequest) -> dict:
    """Emails a 6-digit code and a one-click magic link; either one signs the person in."""
    email = body.email.lower()
    code = await otp.create_code(email)
    token = await signin.create_magic_token(email)
    await signin.send_sign_in_email(email, code, token)
    response: dict = {"sent": True}
    if settings.is_local:
        response["dev_code"] = code  # local convenience only; also visible in Mailpit
    return response


@app.post("/api/v1/auth/otp/verify")
async def verify_otp(body: OtpVerify, session: Session, request: Request, response: Response) -> TokenOut:
    email = body.email.lower()
    if not await otp.verify_code(email, body.code.strip()):
        raise Unauthorized("Invalid or expired code.")
    return await _session_for(session, await _user_for_email(session, email), response, request)


@app.post("/api/v1/auth/magic/verify")
async def verify_magic_link(body: MagicVerify, session: Session, request: Request, response: Response) -> TokenOut:
    email = await signin.consume_magic_token(body.token)
    if email is None:
        raise Unauthorized("This sign-in link has expired or was already used. Request a new one.")
    return await _session_for(session, await _user_for_email(session, email), response, request)


@app.post("/api/v1/auth/google")
async def google_sign_in(body: GoogleSignIn, session: Session, request: Request, response: Response) -> TokenOut:
    try:
        email, name = await asyncio.to_thread(signin.verify_google_id_token, body.credential)
    except signin.GoogleTokenInvalid as exc:
        log.info("google_sign_in_rejected", reason=str(exc)[:100])
        raise Unauthorized("Google sign-in didn't work. Try again or use your email.") from exc
    return await _session_for(session, await _user_for_email(session, email, name), response, request)


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
    if user is None or user.suspended_at or user.deleted_at:
        raise Unauthorized("This account is not available.")
    await session.commit()
    key = await tokens.ensure_active_key(session)
    access, ttl = tokens.issue_access_token(user, key, await _revoked_before(user.id))
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
    await _cut_off_sessions(uuid.UUID(current.id))
    _clear_refresh_cookie(response)


# ─────────────────────────────── the signed-in user ───────────────────────────────
async def _me(session: AsyncSession, current: auth.CurrentUser) -> User:
    user = await session.get(User, uuid.UUID(current.id))
    if user is None or user.deleted_at:
        raise NotFound("User not found.")
    return user


@app.get("/api/v1/me")
async def me(current: CurrentUserDep, session: Session) -> UserOut:
    return UserOut.model_validate(await _me(session, current))


class AgentRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(pattern=r"^\+?[0-9 \-]{8,16}$")
    agency_name: str | None = Field(None, max_length=120)
    rera_agent_id: str | None = Field(None, max_length=40)


@app.post("/api/v1/me/agent-request")
async def request_agent_account(body: AgentRequest, current: CurrentUserDep, session: Session) -> UserOut:
    """T1.16 / Q4: a buyer asks to list homes. They become an unverified agent; an admin checks their
    details (manual KYC for the MVP) and ticks "verified" on the People page before they can publish."""
    user = await _me(session, current)
    if user.role != "buyer":
        raise Conflict("Your account already has agent or admin access.")
    user.name, user.phone = body.name.strip(), body.phone.strip()
    user.agency_name, user.rera_agent_id = body.agency_name, body.rera_agent_id
    user.role, user.agent_verified, user.agent_requested_at = "agent", False, datetime.now(UTC)
    await session.commit()
    await _cut_off_sessions(user.id)  # the new role takes effect on the next token refresh
    return UserOut.model_validate(user)


class DeleteAccount(BaseModel):
    confirm: Literal["DELETE"]


@app.delete("/api/v1/me", status_code=204)
async def delete_account(body: DeleteAccount, current: CurrentUserDep, session: Session, response: Response) -> None:
    """FR-6.4 (DPDP right to erasure). Personal fields are scrubbed now; other services erase their data on
    identity.user_deleted (favourites, saved searches, enquiry contact details, AI logs; an agent's listings
    are archived); the row itself is purged after `account_purge_days`."""
    user = await _me(session, current)
    if user.role == "admin":
        raise Conflict("Administrator accounts can't be deleted from here. Ask another administrator.")
    user.email = f"deleted-{user.id.hex}@deleted.invalid"
    user.name = user.phone = user.agency_name = user.rera_agent_id = None
    user.deleted_at = datetime.now(UTC)
    await tokens.revoke_all_for_user(session, user.id)
    add_event(session, topic=events.IDENTITY_EVENTS, event_type=events.USER_DELETED, subject=str(user.id),
              data={"user_id": str(user.id)}, source="identity")
    await session.commit()
    await _cut_off_sessions(user.id)
    _clear_refresh_cookie(response)


# ─────────────────────────────── admin (FR-7.1) ───────────────────────────────
class RoleUpdate(BaseModel):
    role: Literal["buyer", "agent", "admin"]
    agent_verified: bool = False
    reason: str = Field("Role updated by an administrator.", min_length=3, max_length=500)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class AdminActionOut(BaseModel):
    id: uuid.UUID
    action: str
    detail: str | None
    reason: str
    admin_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


@app.get("/api/v1/admin/users")
async def list_users(_admin: Admin, session: Session, email: str | None = None,
                     pending: bool = Query(False, description="Only agents waiting for verification"),
                     suspended: bool = Query(False, description="Only suspended accounts"),
                     limit: int = Query(50, ge=1, le=200)) -> list[AdminUserOut]:
    """Newest first; `email` filters by substring. Used by the admin page to verify and moderate people."""
    stmt = select(User).where(User.deleted_at.is_(None)).order_by(User.created_at.desc()).limit(limit)
    if email:
        stmt = stmt.where(User.email.ilike(f"%{email.strip().lower()}%"))
    if pending:
        stmt = stmt.where(User.role == "agent", User.agent_verified.is_(False))
    if suspended:
        stmt = stmt.where(User.suspended_at.is_not(None))
    return [AdminUserOut.model_validate(u) for u in await session.scalars(stmt)]


async def _target(session: AsyncSession, user_id: uuid.UUID, admin: auth.CurrentUser) -> User:
    user = await session.get(User, user_id)
    if user is None or user.deleted_at:
        raise NotFound("User not found.")
    if str(user.id) == admin.id:
        raise ValidationFailed("You can't change your own account here.")
    return user


@app.post("/api/v1/admin/users/{user_id}/role")
async def set_role(user_id: uuid.UUID, body: RoleUpdate, admin: Admin, session: Session) -> AdminUserOut:
    user = await _target(session, user_id, admin)
    user.role, user.agent_verified = body.role, body.agent_verified and body.role == "agent"
    detail = f"{body.role}{' (verified)' if user.agent_verified else ''}"
    session.add(AdminAction(user_id=user.id, admin_id=uuid.UUID(admin.id), action="role", detail=detail, reason=body.reason))
    await session.commit()
    await _cut_off_sessions(user_id)  # old tokens carry the old role
    return AdminUserOut.model_validate(user)


@app.post("/api/v1/admin/users/{user_id}/suspend")
async def suspend_user(user_id: uuid.UUID, body: ReasonBody, admin: Admin, session: Session) -> AdminUserOut:
    """Signs the person out everywhere and blocks sign-in; an agent's live listings are hidden (listing
    service, on identity.user_suspended) until they are reinstated."""
    user = await _target(session, user_id, admin)
    if user.suspended_at:
        raise Conflict("This account is already suspended.")
    user.suspended_at = datetime.now(UTC)
    await tokens.revoke_all_for_user(session, user.id)
    session.add(AdminAction(user_id=user.id, admin_id=uuid.UUID(admin.id), action="suspend", reason=body.reason))
    add_event(session, topic=events.IDENTITY_EVENTS, event_type=events.USER_SUSPENDED, subject=str(user.id),
              data={"user_id": str(user.id)}, source="identity")
    await session.commit()
    await _cut_off_sessions(user.id)
    return AdminUserOut.model_validate(user)


@app.post("/api/v1/admin/users/{user_id}/reinstate")
async def reinstate_user(user_id: uuid.UUID, body: ReasonBody, admin: Admin, session: Session) -> AdminUserOut:
    user = await _target(session, user_id, admin)
    if not user.suspended_at:
        raise Conflict("This account is not suspended.")
    user.suspended_at = None
    session.add(AdminAction(user_id=user.id, admin_id=uuid.UUID(admin.id), action="reinstate", reason=body.reason))
    add_event(session, topic=events.IDENTITY_EVENTS, event_type=events.USER_REINSTATED, subject=str(user.id),
              data={"user_id": str(user.id)}, source="identity")
    await session.commit()
    return AdminUserOut.model_validate(user)


@app.get("/api/v1/admin/users/{user_id}/actions")
async def user_actions(user_id: uuid.UUID, _admin: Admin, session: Session) -> list[AdminActionOut]:
    rows = await session.scalars(
        select(AdminAction).where(AdminAction.user_id == user_id).order_by(AdminAction.created_at.desc())
    )
    return [AdminActionOut.model_validate(r) for r in rows]


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
    if user is None or user.deleted_at:
        raise NotFound("User not found.")
    return UserOut.model_validate(user)


@app.get("/internal/users/by-email/{email}")
async def internal_get_user_by_email(email: str, session: Session) -> UserOut:
    user = await session.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        raise NotFound("User not found.")
    return UserOut.model_validate(user)
