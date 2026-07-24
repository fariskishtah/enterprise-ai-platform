"""Company-scoped customer support request persistence."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base


class SupportRequestStatus(StrEnum):
    SUBMITTED = "submitted"
    DELIVERED = "delivered"
    DELIVERY_FAILED = "delivery_failed"
    CLOSED = "closed"


class SupportRequest(Base):
    """A bounded support request and its delivery state."""

    __tablename__ = "support_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('submitted', 'delivered', 'delivery_failed', 'closed')",
            name="ck_support_requests_status",
        ),
        CheckConstraint(
            "delivery_attempts >= 0 AND delivery_attempts <= 5",
            name="ck_support_requests_delivery_attempts",
        ),
        Index(
            "uq_support_request_actor_idempotency",
            "company_id",
            "created_by",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "ix_support_request_company_created",
            "company_id",
            "created_at",
        ),
        Index("ix_support_request_company_status", "company_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    factory_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("factories.id", ondelete="RESTRICT")
    )
    machine_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="RESTRICT")
    )
    requester_name: Mapped[str] = mapped_column(String(160), nullable=False)
    requester_email: Mapped[str] = mapped_column(String(320), nullable=False)
    requester_role: Mapped[str] = mapped_column(String(32), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    current_page: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SupportRequestStatus.SUBMITTED.value
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    delivery_attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
