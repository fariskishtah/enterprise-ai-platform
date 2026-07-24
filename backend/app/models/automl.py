"""Durable AutoML study, trial, and future execution-slot entities."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLAlchemyEnum
from sqlalchemy.types import Uuid

from app.db.base import Base
from app.ml.automl.metrics import MetricDirection
from app.ml.automl.models import AutoMLStudyStatus, AutoMLTrialStatus, SamplerType
from app.ml.domain import TaskType
from app.models.ai_governance import TrainingJob, _enum_values
from app.models.user import User


class AutoMLStudy(Base):
    """Authoritative management state for one AutoML study."""

    __tablename__ = "automl_studies"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_automl_studies_status",
        ),
        CheckConstraint(
            "task_type IN ('classification','regression')",
            name="ck_automl_studies_task",
        ),
        CheckConstraint(
            "metric_direction IN ('maximize','minimize')",
            name="ck_automl_studies_direction",
        ),
        CheckConstraint("sampler_type = 'random'", name="ck_automl_studies_sampler"),
        CheckConstraint(
            "trial_budget BETWEEN 1 AND 100", name="ck_automl_studies_trial_budget"
        ),
        CheckConstraint(
            "cross_validation_folds BETWEEN 2 AND 10", name="ck_automl_studies_cv_folds"
        ),
        CheckConstraint(
            "time_budget_seconds BETWEEN 60 AND 86400",
            name="ck_automl_studies_time_budget",
        ),
        CheckConstraint(
            "per_trial_timeout_seconds BETWEEN 10 AND 21600 AND "
            "per_trial_timeout_seconds <= time_budget_seconds",
            name="ck_automl_studies_trial_timeout",
        ),
        CheckConstraint(
            "max_concurrent_trials BETWEEN 1 AND 4 AND "
            "max_concurrent_trials <= trial_budget",
            name="ck_automl_studies_concurrency",
        ),
        CheckConstraint("state_version >= 0", name="ck_automl_studies_state_version"),
        CheckConstraint(
            "register_champion = false OR registered_model_name IS NOT NULL",
            name="ck_automl_studies_champion_name",
        ),
        CheckConstraint(
            "registered_model_name IS NULL OR "
            "length(registered_model_name) BETWEEN 3 AND 128",
            name="ck_automl_studies_model_name_length",
        ),
        UniqueConstraint(
            "requested_by_user_id",
            "idempotency_key",
            name="uq_automl_studies_scoped_idempotency",
        ),
        Index(
            "ix_automl_studies_requester_created", "requested_by_user_id", "created_at"
        ),
        Index("ix_automl_studies_company_created", "company_id", "created_at"),
        Index("ix_automl_studies_dataset_version", "dataset_version_id"),
        Index("ix_automl_studies_status_created", "status", "created_at"),
        Index("ix_automl_studies_task_created", "task_type", "created_at"),
        Index("ix_automl_studies_reconciliation", "status", "deadline_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    requested_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    dataset_version_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
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
    status: Mapped[AutoMLStudyStatus] = mapped_column(
        SQLAlchemyEnum(
            AutoMLStudyStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
        default=AutoMLStudyStatus.QUEUED,
        server_default="queued",
    )
    primary_metric: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_direction: Mapped[MetricDirection] = mapped_column(
        SQLAlchemyEnum(
            MetricDirection,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=16,
        ),
        nullable=False,
    )
    sampler_type: Mapped[SamplerType] = mapped_column(
        SQLAlchemyEnum(
            SamplerType,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=16,
        ),
        nullable=False,
        default=SamplerType.RANDOM,
        server_default="random",
    )
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    plugin_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    search_spaces: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    preprocessing: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    data_specification: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    cross_validation_folds: Mapped[int] = mapped_column(Integer, nullable=False)
    trial_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    time_budget_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    per_trial_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_concurrent_trials: Mapped[int] = mapped_column(Integer, nullable=False)
    register_champion: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="0"
    )
    registered_model_name: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    queue_message_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    best_trial_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "automl_trials.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_automl_studies_best_trial",
        ),
    )
    champion_training_job_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("training_jobs.id", ondelete="SET NULL")
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    safe_error_message: Mapped[str | None] = mapped_column(Text)

    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_user_id])
    trials: Mapped[list[AutoMLTrial]] = relationship(
        back_populates="study",
        cascade="all, delete-orphan",
        foreign_keys="AutoMLTrial.study_id",
    )
    best_trial: Mapped[AutoMLTrial | None] = relationship(
        foreign_keys=[best_trial_id], post_update=True
    )
    champion_training_job: Mapped[TrainingJob | None] = relationship(
        foreign_keys=[champion_training_job_id]
    )


class AutoMLTrial(Base):
    """Persisted lifecycle and result snapshot for one future study trial."""

    __tablename__ = "automl_trials"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','pruned','cancelled')",
            name="ck_automl_trials_status",
        ),
        CheckConstraint("trial_number >= 0", name="ck_automl_trials_number"),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 10 AND "
            "attempt_count <= max_attempts",
            name="ck_automl_trials_attempts",
        ),
        CheckConstraint("state_version >= 0", name="ck_automl_trials_state_version"),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_automl_trials_duration",
        ),
        CheckConstraint(
            "primary_metric_value IS NULL OR "
            "primary_metric_value BETWEEN -1e308 AND 1e308",
            name="ck_automl_trials_metric_finite",
        ),
        UniqueConstraint(
            "study_id", "trial_number", name="uq_automl_trials_study_number"
        ),
        UniqueConstraint(
            "study_id",
            "plugin_id",
            "parameter_fingerprint",
            name="uq_automl_trials_study_plugin_fingerprint",
        ),
        Index("ix_automl_trials_study_status", "study_id", "status"),
        Index("ix_automl_trials_study_plugin", "study_id", "plugin_id"),
        Index("ix_automl_trials_study_metric", "study_id", "primary_metric_value"),
        Index("ix_automl_trials_lease", "lease_expires_at"),
        Index("ix_automl_trials_queue_message", "queue_message_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    study_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("automl_studies.id", ondelete="CASCADE"),
        nullable=False,
    )
    trial_number: Mapped[int] = mapped_column(Integer, nullable=False)
    plugin_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[AutoMLTrialStatus] = mapped_column(
        SQLAlchemyEnum(
            AutoMLTrialStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
        default=AutoMLTrialStatus.QUEUED,
        server_default="queued",
    )
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    parameter_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    queue_message_id: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fold_metrics: Mapped[list[dict[str, float]] | None] = mapped_column(JSON)
    aggregate_metrics: Mapped[dict[str, float] | None] = mapped_column(JSON)
    primary_metric_value: Mapped[float | None] = mapped_column(Float)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(64))
    safe_error_message: Mapped[str | None] = mapped_column(Text)

    study: Mapped[AutoMLStudy] = relationship(
        back_populates="trials", foreign_keys=[study_id]
    )


class AutoMLExecutionSlot(Base):
    """Future durable concurrency lease primitive; no claiming behavior yet."""

    __tablename__ = "automl_execution_slots"
    __table_args__ = (
        CheckConstraint("slot_number > 0", name="ck_automl_slots_number"),
        CheckConstraint("state_version >= 0", name="ck_automl_slots_state_version"),
    )

    slot_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    trial_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("automl_trials.id", ondelete="SET NULL"),
        unique=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    trial: Mapped[AutoMLTrial | None] = relationship()
