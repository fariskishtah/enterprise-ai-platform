"""Persistent prediction events and immutable model reference profiles."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
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
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Enum as SQLAlchemyEnum
from sqlalchemy.types import Uuid

from app.db.base import Base
from app.ml.domain import AlgorithmType, TaskType
from app.ml.monitoring.models import PredictionEventStatus, ReferenceProfileSource


def _enum_values[EnumT: StrEnum](enum_type: type[EnumT]) -> list[str]:
    return [str(value) for value in enum_type]


class PredictionEventEntity(Base):
    """Durable summaries for one completed prediction API request."""

    __tablename__ = "prediction_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_prediction_events_status_valid",
        ),
        CheckConstraint(
            "duration_ms >= 0",
            name="ck_prediction_events_duration_nonnegative",
        ),
        CheckConstraint(
            "row_count >= 0 AND feature_count >= 0",
            name="ck_prediction_events_dimensions_nonnegative",
        ),
        CheckConstraint(
            "status != 'succeeded' OR row_count > 0",
            name="ck_prediction_events_success_rows_positive",
        ),
        CheckConstraint(
            "algorithm IN ('random_forest','logistic_regression','decision_tree',"
            "'extra_trees','knn','svm','gradient_boosting','linear_regression',"
            "'ridge','lasso','elastic_net','xgboost','lightgbm','catboost')",
            name="ck_prediction_events_algorithm_valid",
        ),
        CheckConstraint(
            "task_type IN ('regression', 'classification')",
            name="ck_prediction_events_task_type_valid",
        ),
        Index("ix_prediction_events_model_name", "registered_model_name"),
        Index(
            "ix_prediction_events_model_version",
            "registered_model_name",
            "resolved_model_version",
        ),
        Index("ix_prediction_events_task_type", "task_type"),
        Index("ix_prediction_events_status", "status"),
        Index("ix_prediction_events_created_at", "created_at"),
        Index("ix_prediction_events_requested_by", "requested_by_user_id"),
        Index("ix_prediction_events_company_time", "company_id", "created_at"),
        Index(
            "ix_prediction_events_model_window",
            "registered_model_name",
            "resolved_model_version",
            "created_at",
        ),
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
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    registered_model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_model_reference: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    resolved_model_version: Mapped[str | None] = mapped_column(String(128))
    resolved_aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False)
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
    status: Mapped[PredictionEventStatus] = mapped_column(
        SQLAlchemyEnum(
            PredictionEventStatus,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    feature_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    feature_profile: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
    )
    prediction_profile: Mapped[dict[str, object] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    safe_error_message: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class ModelReferenceProfileEntity(Base):
    """Immutable fixed-bin profile owned by one registered model version."""

    __tablename__ = "model_reference_profiles"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "registered_model_name",
            "model_version",
            name="uq_model_reference_profiles_version",
        ),
        CheckConstraint(
            "source = 'evaluation'",
            name="ck_model_reference_profiles_source_valid",
        ),
        CheckConstraint(
            "feature_count > 0 AND sample_count > 0",
            name="ck_model_reference_profiles_dimensions_positive",
        ),
        CheckConstraint(
            "algorithm IN ('random_forest','logistic_regression','decision_tree',"
            "'extra_trees','knn','svm','gradient_boosting','linear_regression',"
            "'ridge','lasso','elastic_net','xgboost','lightgbm','catboost')",
            name="ck_model_reference_profiles_algorithm_valid",
        ),
        CheckConstraint(
            "task_type IN ('regression', 'classification')",
            name="ck_model_reference_profiles_task_type_valid",
        ),
        Index(
            "ix_model_reference_profiles_model_version",
            "company_id",
            "registered_model_name",
            "model_version",
            unique=True,
        ),
        Index(
            "ix_model_reference_profiles_training_job",
            "training_job_id",
            unique=True,
        ),
        Index(
            "ix_model_reference_profiles_company_model",
            "company_id",
            "registered_model_name",
            "model_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    registered_model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
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
    source: Mapped[ReferenceProfileSource] = mapped_column(
        SQLAlchemyEnum(
            ReferenceProfileSource,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    feature_count: Mapped[int] = mapped_column(Integer, nullable=False)
    feature_profiles: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
    )
    prediction_profile: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
    )
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    training_job_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("training_jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
