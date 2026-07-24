"""ORM entities for monitoring evaluations, alerts, locks, and outcomes."""

from __future__ import annotations

from datetime import datetime
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
from app.ml.monitoring.evaluation_models import (
    MonitoringAlertSeverity,
    MonitoringAlertStatus,
    MonitoringAlertType,
    MonitoringEvaluationStatus,
    MonitoringEvaluationTrigger,
    PredictionOutcomeType,
)
from app.models.ai_governance import _enum_values


class ModelMonitoringEvaluationEntity(Base):
    __tablename__ = "model_monitoring_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "registered_model_name",
            "model_version",
            "window_start",
            "window_end",
            name="uq_monitoring_evaluation_model_window",
        ),
        UniqueConstraint(
            "idempotency_key", name="uq_monitoring_evaluation_idempotency"
        ),
        CheckConstraint(
            "window_start < window_end", name="ck_monitoring_evaluation_window"
        ),
        CheckConstraint(
            "evaluated_sample_count >= 0 AND successful_prediction_count >= 0 "
            "AND failed_prediction_count >= 0 AND warning_count >= 0 "
            "AND critical_count >= 0",
            name="ck_monitoring_evaluation_counts",
        ),
        Index(
            "ix_monitoring_evaluation_model_version_time",
            "registered_model_name",
            "model_version",
            "window_end",
        ),
        Index("ix_monitoring_evaluation_status_time", "overall_status", "created_at"),
        Index("ix_monitoring_evaluation_company_time", "company_id", "created_at"),
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
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    model_alias: Mapped[str | None] = mapped_column(String(128))
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
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    evaluated_sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    successful_prediction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_prediction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    data_quality_status: Mapped[MonitoringEvaluationStatus] = mapped_column(
        SQLAlchemyEnum(
            MonitoringEvaluationStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    feature_drift_status: Mapped[MonitoringEvaluationStatus] = mapped_column(
        SQLAlchemyEnum(
            MonitoringEvaluationStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    prediction_drift_status: Mapped[MonitoringEvaluationStatus] = mapped_column(
        SQLAlchemyEnum(
            MonitoringEvaluationStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    operational_health_status: Mapped[MonitoringEvaluationStatus] = mapped_column(
        SQLAlchemyEnum(
            MonitoringEvaluationStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    overall_status: Mapped[MonitoringEvaluationStatus] = mapped_column(
        SQLAlchemyEnum(
            MonitoringEvaluationStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    report_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    report: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False)
    critical_count: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[MonitoringEvaluationTrigger] = mapped_column(
        SQLAlchemyEnum(
            MonitoringEvaluationTrigger,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class MonitoringAlertEntity(Base):
    __tablename__ = "monitoring_alerts"
    __table_args__ = (
        UniqueConstraint("deduplication_key", name="uq_monitoring_alert_deduplication"),
        CheckConstraint("occurrence_count > 0", name="ck_monitoring_alert_occurrences"),
        Index(
            "ix_monitoring_alert_model_status",
            "registered_model_name",
            "model_version",
            "status",
        ),
        Index("ix_monitoring_alert_severity_time", "severity", "last_detected_at"),
        Index("ix_monitoring_alert_evaluation", "monitoring_evaluation_id"),
        Index("ix_monitoring_alert_company_status", "company_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    factory_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("factories.id", ondelete="SET NULL")
    )
    machine_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="SET NULL")
    )
    alert_type: Mapped[MonitoringAlertType] = mapped_column(
        SQLAlchemyEnum(
            MonitoringAlertType,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=64,
        ),
        nullable=False,
    )
    severity: Mapped[MonitoringAlertSeverity] = mapped_column(
        SQLAlchemyEnum(
            MonitoringAlertSeverity,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    registered_model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    monitoring_evaluation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_monitoring_evaluations.id", ondelete="SET NULL"),
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    safe_summary: Mapped[str] = mapped_column(Text, nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[MonitoringAlertStatus] = mapped_column(
        SQLAlchemyEnum(
            MonitoringAlertStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    operator_note: Mapped[str | None] = mapped_column(Text)
    engineer_note: Mapped[str | None] = mapped_column(Text)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class MonitoringJobLockEntity(Base):
    __tablename__ = "monitoring_job_locks"

    lock_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class PredictionOutcomeEntity(Base):
    __tablename__ = "prediction_outcomes"
    __table_args__ = (
        UniqueConstraint("prediction_event_id", name="uq_prediction_outcome_event"),
        UniqueConstraint(
            "external_reference_key", name="uq_prediction_outcome_external_reference"
        ),
        Index("ix_prediction_outcome_maturity", "label_maturity_at"),
        Index("ix_prediction_outcome_type", "outcome_type"),
        Index("ix_prediction_outcome_company", "company_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    prediction_event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("prediction_events.id", ondelete="RESTRICT"),
        nullable=False,
    )
    outcome_type: Mapped[PredictionOutcomeType] = mapped_column(
        SQLAlchemyEnum(
            PredictionOutcomeType,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    actual_value: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    label_maturity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    safe_metadata: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    external_reference_key: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
