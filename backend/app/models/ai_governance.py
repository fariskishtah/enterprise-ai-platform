"""Persistent background-training and model-promotion records."""

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
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Enum as SQLAlchemyEnum
from sqlalchemy.types import Uuid

from app.db.base import Base
from app.ml.domain import AlgorithmType, TaskType
from app.ml.jobs.models import TrainingJobStatus
from app.ml.promotion.models import (
    ModelAlias,
    PromotionAction,
    PromotionDecision,
    PromotionOperationOutcome,
)


def _enum_values[EnumT: StrEnum](enum_type: type[EnumT]) -> list[str]:
    return [str(value) for value in enum_type]


class TrainingJob(Base):
    """Authoritative execution state for one queued AI training request."""

    __tablename__ = "training_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_training_jobs_status_valid",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts",
            name="ck_training_jobs_attempts_valid",
        ),
        CheckConstraint(
            "state_version >= 0",
            name="ck_training_jobs_state_version_nonnegative",
        ),
        UniqueConstraint(
            "requested_by_user_id",
            "algorithm",
            "task_type",
            "idempotency_key",
            name="uq_training_jobs_scoped_idempotency",
        ),
        Index("ix_training_jobs_requested_by_user_id", "requested_by_user_id"),
        Index("ix_training_jobs_status", "status"),
        Index("ix_training_jobs_created_at", "created_at"),
        Index("ix_training_jobs_status_started_at", "status", "started_at"),
        Index(
            "ix_training_jobs_model_version",
            "registered_model_name",
            "registered_model_version",
        ),
        Index("ix_training_jobs_queue_message_id", "queue_message_id", unique=True),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    requested_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    algorithm: Mapped[AlgorithmType] = mapped_column(
        SQLAlchemyEnum(
            AlgorithmType,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    task_type: Mapped[TaskType] = mapped_column(
        SQLAlchemyEnum(
            TaskType,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    status: Mapped[TrainingJobStatus] = mapped_column(
        SQLAlchemyEnum(
            TrainingJobStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
        default=TrainingJobStatus.QUEUED,
        server_default=TrainingJobStatus.QUEUED.value,
    )
    specification: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    experiment_name: Mapped[str] = mapped_column(String(length=255), nullable=False)
    run_name: Mapped[str | None] = mapped_column(String(length=255))
    registered_model_name: Mapped[str] = mapped_column(
        String(length=128),
        nullable=False,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(length=128))
    request_fingerprint: Mapped[str] = mapped_column(String(length=64), nullable=False)
    queue_message_id: Mapped[str | None] = mapped_column(String(length=255))
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    state_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(length=64))
    safe_error_message: Mapped[str | None] = mapped_column(Text)
    local_execution_run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    mlflow_experiment_id: Mapped[str | None] = mapped_column(String(length=255))
    mlflow_run_id: Mapped[str | None] = mapped_column(String(length=255))
    registered_model_version: Mapped[str | None] = mapped_column(String(length=128))
    metrics: Mapped[dict[str, float] | None] = mapped_column(JSON)


class ModelPromotionAudit(Base):
    """Append-only application audit for one governed alias attempt."""

    __tablename__ = "model_promotion_audits"
    __table_args__ = (
        CheckConstraint(
            "action = 'assign_alias'",
            name="ck_model_promotion_audits_action_valid",
        ),
        CheckConstraint(
            "target_alias IN ('challenger', 'champion')",
            name="ck_model_promotion_audits_alias_valid",
        ),
        CheckConstraint(
            "decision IN ('approved', 'rejected', 'overridden')",
            name="ck_model_promotion_audits_decision_valid",
        ),
        CheckConstraint(
            "operation_outcome IN ('pending', 'succeeded', 'failed')",
            name="ck_model_promotion_audits_outcome_valid",
        ),
        Index("ix_model_promotion_audits_model_name", "registered_model_name"),
        Index("ix_model_promotion_audits_requested_by", "requested_by_user_id"),
        Index("ix_model_promotion_audits_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    registered_model_name: Mapped[str] = mapped_column(
        String(length=128),
        nullable=False,
    )
    model_version: Mapped[str] = mapped_column(String(length=128), nullable=False)
    algorithm: Mapped[AlgorithmType] = mapped_column(
        SQLAlchemyEnum(
            AlgorithmType,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    task_type: Mapped[TaskType] = mapped_column(
        SQLAlchemyEnum(
            TaskType,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    action: Mapped[PromotionAction] = mapped_column(
        SQLAlchemyEnum(
            PromotionAction,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=64,
        ),
        nullable=False,
        default=PromotionAction.ASSIGN_ALIAS,
        server_default=PromotionAction.ASSIGN_ALIAS.value,
    )
    target_alias: Mapped[ModelAlias] = mapped_column(
        SQLAlchemyEnum(
            ModelAlias,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    previous_version: Mapped[str | None] = mapped_column(String(length=128))
    requested_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    decision: Mapped[PromotionDecision] = mapped_column(
        SQLAlchemyEnum(
            PromotionDecision,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    policy_result: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    force: Mapped[bool] = mapped_column(nullable=False, default=False)
    reason: Mapped[str | None] = mapped_column(Text)
    operation_outcome: Mapped[PromotionOperationOutcome] = mapped_column(
        SQLAlchemyEnum(
            PromotionOperationOutcome,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
        default=PromotionOperationOutcome.PENDING,
        server_default=PromotionOperationOutcome.PENDING.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(length=64))
    safe_error_message: Mapped[str | None] = mapped_column(Text)
