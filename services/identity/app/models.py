import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from estate_common.db import Base
from estate_common.outbox import OutboxMessage  # noqa: F401 — registers the outbox table for migrations


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20))  # PII: never sent to LLMs
    role: Mapped[str] = mapped_column(String(10), default="buyer")  # buyer | agent | admin
    agent_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Agent application (T1.16): an admin verifies these before the agent can list.
    agency_name: Mapped[str | None] = mapped_column(String(120))
    rera_agent_id: Mapped[str | None] = mapped_column(String(40))
    agent_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Account deletion (FR-6.4): personal fields are scrubbed at once; the row is purged after 30 days.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SigningKey(Base):
    """RS256 key pair. The newest non-retired key signs; retired keys stay in JWKS until tokens signed
    with them have expired. Local dev keeps the private key here — production uses Azure Key Vault (ADR-0015)."""

    __tablename__ = "signing_keys"

    kid: Mapped[str] = mapped_column(String(64), primary_key=True)
    private_pem: Mapped[str] = mapped_column(Text)
    public_jwk: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(Base):
    """Opaque refresh tokens, stored hashed. Each use rotates the token within its family; presenting an
    already-rotated token means it was stolen, so the whole family is revoked (reuse detection)."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    user_agent: Mapped[str | None] = mapped_column(String(200))


class AdminAction(Base):
    """Audit log for admin actions on people (FR-7.1): suspend, reinstate, role changes. Reason required."""

    __tablename__ = "admin_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    admin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(20))  # suspend | reinstate | role
    detail: Mapped[str | None] = mapped_column(String(60))  # e.g. the new role
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
