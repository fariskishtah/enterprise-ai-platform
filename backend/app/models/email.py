"""Durable transactional email state."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base


class EmailMessageType(StrEnum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"
    WELCOME = "welcome"
    TEAM_INVITATION = "team_invitation"
    FEEDBACK_RECEIVED = "feedback_received"
    SUPPORT_REQUEST_RECEIVED = "support_request_received"
    SUBSCRIPTION_CONFIRMATION = "subscription_confirmation"
    PAYMENT_CONFIRMATION = "payment_confirmation"
    PAYMENT_FAILURE = "payment_failure"
    SUBSCRIPTION_CANCELLATION = "subscription_cancellation"


class EmailDeliveryStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    RETRYING = "retrying"
    CAPTURED = "captured"
    SENT = "sent"
    FAILED = "failed"


class OutboundEmailMessage(Base):
    """Authoritative state and payload for one bounded delivery workflow."""

    __tablename__ = "outbound_email_messages"
    __table_args__ = (
        CheckConstraint(
            "message_type IN ('email_verification','password_reset','welcome',"
            "'team_invitation','feedback_received','support_request_received',"
            "'subscription_confirmation','payment_confirmation','payment_failure',"
            "'subscription_cancellation')",
            name="ck_outbound_email_message_type",
        ),
        CheckConstraint(
            "status IN ('queued','processing','retrying','captured','sent','failed')",
            name="ck_outbound_email_status",
        ),
        CheckConstraint(
            "retry_count >= 0 AND retry_count <= max_retries",
            name="ck_outbound_email_retry_bound",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= max_retries + 1",
            name="ck_outbound_email_attempt_bound",
        ),
        CheckConstraint(
            "max_retries >= 1 AND max_retries <= 10",
            name="ck_outbound_email_max_retries",
        ),
        Index("ix_outbound_email_status_next", "status", "next_attempt_at"),
        Index("ix_outbound_email_company_created", "company_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT")
    )
    message_type: Mapped[str] = mapped_column(String(48), nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    from_address: Mapped[str] = mapped_column(String(320), nullable=False)
    from_name: Mapped[str] = mapped_column(String(100), nullable=False)
    reply_to: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    text_body: Mapped[str] = mapped_column(Text, nullable=False)
    html_body: Mapped[str] = mapped_column(Text, nullable=False)
    payload_encrypted: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=EmailDeliveryStatus.QUEUED.value
    )
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(nullable=False, default=3)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(255))
    deduplication_key: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    related_resource_type: Mapped[str | None] = mapped_column(String(64))
    related_resource_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
