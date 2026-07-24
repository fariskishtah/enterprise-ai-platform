"""Persistent policy, request, and audit records for controlled retraining."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
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
from app.ml.monitoring import DriftSeverity
from app.ml.retraining.models import (
    RetrainingDecisionStatus,
    RetrainingEvaluationMode,
    RetrainingRequestStatus,
    RetrainingTriggerType,
)
from app.models.ai_governance import _enum_values


class ModelRetrainingPolicy(Base):
    """One current, validated policy for a registered-model name."""

    __tablename__ = "model_retraining_policies"
    __table_args__ = (
        CheckConstraint("cooldown_seconds >= 0", name="ck_retraining_policy_cooldown"),
        CheckConstraint(
            "minimum_drift_status IN ('warning', 'critical')",
            name="ck_retraining_policy_drift_status",
        ),
        CheckConstraint(
            "minimum_current_sample_count > 0 AND maximum_requests_per_day > 0 "
            "AND maximum_requests_per_week > 0 AND maximum_active_requests > 0",
            name="ck_retraining_policy_positive_limits",
        ),
        UniqueConstraint(
            "company_id",
            "registered_model_name",
            name="uq_retraining_policy_model_name",
        ),
        Index("ix_retraining_policy_enabled", "enabled"),
        Index("ix_retraining_policy_company", "company_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    registered_model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allowed_trigger_types: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    minimum_drift_status: Mapped[DriftSeverity] = mapped_column(
        SQLAlchemyEnum(
            DriftSeverity,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    minimum_current_sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_requests_per_day: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_requests_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_active_requests: Mapped[int] = mapped_column(Integer, nullable=False)
    require_champion_source: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allow_truncated_drift: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ModelRetrainingRequest(Base):
    """Durable link from one accepted decision to one existing training job."""

    __tablename__ = "model_retraining_requests"
    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('feature_drift', 'prediction_drift', "
            "'data_quality', 'manual')",
            name="ck_retraining_request_trigger_type",
        ),
        CheckConstraint(
            "decision_status IN ('eligible', 'not_eligible', "
            "'blocked_cooldown', 'blocked_duplicate', 'blocked_quota', "
            "'blocked_insufficient_data', 'blocked_missing_profile', "
            "'blocked_missing_training_evidence', 'disabled')",
            name="ck_retraining_request_decision_status",
        ),
        CheckConstraint(
            "request_status IN ('pending', 'submitted', 'training', "
            "'candidate_created', 'completed', 'failed', 'cancelled')",
            name="ck_retraining_request_status",
        ),
        CheckConstraint(
            "evaluation_mode IN ('automatic', 'manual')",
            name="ck_retraining_request_mode",
        ),
        UniqueConstraint("idempotency_key", name="uq_retraining_request_idempotency"),
        UniqueConstraint("training_job_id", name="uq_retraining_request_training_job"),
        UniqueConstraint(
            "monitoring_evaluation_id",
            name="uq_retraining_request_monitoring_evaluation",
        ),
        Index(
            "ix_retraining_request_model_status",
            "registered_model_name",
            "request_status",
        ),
        Index("ix_retraining_request_requested_at", "requested_at"),
        Index("ix_retraining_request_policy", "policy_id"),
        Index("ix_retraining_request_company", "company_id", "requested_at"),
        Index(
            "ix_retraining_request_monitoring_evaluation",
            "monitoring_evaluation_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    registered_model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_training_job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("training_jobs.id", ondelete="RESTRICT"),
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
    trigger_type: Mapped[RetrainingTriggerType] = mapped_column(
        SQLAlchemyEnum(
            RetrainingTriggerType,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    trigger_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    policy_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_retraining_policies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    decision_status: Mapped[RetrainingDecisionStatus] = mapped_column(
        SQLAlchemyEnum(
            RetrainingDecisionStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=48,
        ),
        nullable=False,
    )
    request_status: Mapped[RetrainingRequestStatus] = mapped_column(
        SQLAlchemyEnum(
            RetrainingRequestStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    evaluation_mode: Mapped[RetrainingEvaluationMode] = mapped_column(
        SQLAlchemyEnum(
            RetrainingEvaluationMode,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    training_job_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("training_jobs.id", ondelete="RESTRICT")
    )
    monitoring_evaluation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_monitoring_evaluations.id", ondelete="RESTRICT"),
    )
    resulting_model_version: Mapped[str | None] = mapped_column(String(128))
    requested_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text)
    override_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safe_failure_code: Mapped[str | None] = mapped_column(String(64))
    safe_failure_message: Mapped[str | None] = mapped_column(Text)
    comparison: Mapped[dict[str, object] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ModelRetrainingAudit(Base):
    """Append-only bounded evidence for every retraining evaluation."""

    __tablename__ = "model_retraining_audits"
    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('feature_drift', 'prediction_drift', "
            "'data_quality', 'manual')",
            name="ck_retraining_audit_trigger_type",
        ),
        CheckConstraint(
            "decision_status IN ('eligible', 'not_eligible', "
            "'blocked_cooldown', 'blocked_duplicate', 'blocked_quota', "
            "'blocked_insufficient_data', 'blocked_missing_profile', "
            "'blocked_missing_training_evidence', 'disabled')",
            name="ck_retraining_audit_decision_status",
        ),
        CheckConstraint(
            "evaluation_mode IN ('automatic', 'manual')",
            name="ck_retraining_audit_mode",
        ),
        Index("ix_retraining_audit_model", "registered_model_name"),
        Index("ix_retraining_audit_evaluated_at", "evaluated_at"),
        Index("ix_retraining_audit_evaluator", "evaluated_by_user_id"),
        Index("ix_retraining_audit_company", "company_id", "evaluated_at"),
        Index(
            "ix_retraining_audit_monitoring_evaluation",
            "monitoring_evaluation_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    registered_model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_model_version: Mapped[str | None] = mapped_column(String(128))
    requested_alias: Mapped[str | None] = mapped_column(String(128))
    trigger_type: Mapped[RetrainingTriggerType] = mapped_column(
        SQLAlchemyEnum(
            RetrainingTriggerType,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    trigger_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    policy_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_retraining_policies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    decision_status: Mapped[RetrainingDecisionStatus] = mapped_column(
        SQLAlchemyEnum(
            RetrainingDecisionStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=48,
        ),
        nullable=False,
    )
    decision_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    drift_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    thresholds: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    cooldown_state: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    quota_state: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    existing_request_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_retraining_requests.id", ondelete="SET NULL"),
    )
    created_request_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_retraining_requests.id", ondelete="SET NULL"),
    )
    monitoring_evaluation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_monitoring_evaluations.id", ondelete="RESTRICT"),
    )
    evaluated_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    evaluation_mode: Mapped[RetrainingEvaluationMode] = mapped_column(
        SQLAlchemyEnum(
            RetrainingEvaluationMode,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    override_used: Mapped[bool] = mapped_column(Boolean, nullable=False)
    override_reason: Mapped[str | None] = mapped_column(Text)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
