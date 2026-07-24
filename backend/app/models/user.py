"""User and authentication token ORM models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLAlchemyEnum
from sqlalchemy.types import Uuid

from app.db.base import Base


class UserRole(StrEnum):
    """Roles supported by the platform authorization model."""

    ADMIN = "admin"
    ENGINEER = "engineer"
    OPERATOR = "operator"


def _role_values(enum_type: type[UserRole]) -> list[str]:
    """Return persisted role enum values."""
    return [role.value for role in enum_type]


class User(Base):
    """Application user."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'engineer', 'operator')",
            name="ck_users_role_valid",
        ),
        Index("ix_users_email", "email", unique=True),
        Index("ix_users_company_role", "company_id", "role"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    email: Mapped[str] = mapped_column(String(length=320), nullable=False)
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(String(length=255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SQLAlchemyEnum(
            UserRole,
            values_callable=_role_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
        default=UserRole.OPERATOR,
        server_default=UserRole.OPERATOR.value,
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    company: Mapped[Company] = relationship(back_populates="users")
    password_reset_tokens: Mapped[list[PasswordResetToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RefreshToken(Base):
    """Persisted refresh token metadata for rotation and revocation."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_jti", "jti", unique=True),
        Index("ix_refresh_tokens_token_hash", "token_hash", unique=True),
        Index("ix_refresh_tokens_user_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    jti: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(length=64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent_summary: Mapped[str | None] = mapped_column(String(length=255))
    source_ip: Mapped[str | None] = mapped_column(String(length=64))

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class PasswordResetToken(Base):
    """Hashed, expiring, single-use password reset credential."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        Index("ix_password_reset_tokens_hash", "token_hash", unique=True),
        Index("ix_password_reset_tokens_user_expiry", "user_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(length=64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="password_reset_tokens")


class AuditEvent(Base):
    """Immutable, append-only, tenant-scoped security and operations event."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "result IN ('success', 'failure')", name="ck_audit_events_result"
        ),
        Index("ix_audit_events_company_time", "company_id", "occurred_at"),
        Index("ix_audit_events_company_action", "company_id", "action"),
        Index("ix_audit_events_resource", "resource_type", "resource_id"),
        Index("ix_audit_events_actor", "actor_user_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_role: Mapped[str | None] = mapped_column(String(length=32))
    action: Mapped[str] = mapped_column(String(length=128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(length=64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(length=128))
    result: Mapped[str] = mapped_column(String(length=16), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(length=128))
    correlation_id: Mapped[str | None] = mapped_column(String(length=128))
    source_ip: Mapped[str | None] = mapped_column(String(length=64))
    user_agent: Mapped[str | None] = mapped_column(String(length=255))
    safe_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    before_summary: Mapped[str | None] = mapped_column(Text)
    after_summary: Mapped[str | None] = mapped_column(Text)
    retention_class: Mapped[str] = mapped_column(
        String(length=32), nullable=False, default="security", server_default="security"
    )


from app.models.manufacturing import Company  # noqa: E402
