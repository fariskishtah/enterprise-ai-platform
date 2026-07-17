"""MLOps experiment management ORM models."""

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
from app.models.user import User


class TrainingRunStatus(StrEnum):
    """Lifecycle states for future model training runs."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


def _training_run_status_values(
    enum_type: type[TrainingRunStatus],
) -> list[str]:
    """Return persisted training run status values."""
    return [status.value for status in enum_type]


class Experiment(Base):
    """MLOps experiment grouping future training runs."""

    __tablename__ = "experiments"
    __table_args__ = (
        Index("ix_experiments_name", "name", unique=True),
        Index("ix_experiments_created_by", "created_by"),
        Index("ix_experiments_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    name: Mapped[str] = mapped_column(String(length=255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    created_by_user: Mapped[User] = relationship("User")
    training_runs: Mapped[list[TrainingRun]] = relationship(
        "TrainingRun",
        back_populates="experiment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TrainingRun(Base):
    """Metadata for a future model training run."""

    __tablename__ = "training_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELED')",
            name="ck_training_runs_status_valid",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_training_runs_finished_after_started",
        ),
        Index("ix_training_runs_experiment_id", "experiment_id"),
        Index("ix_training_runs_dataset_version", "dataset_version"),
        Index("ix_training_runs_algorithm", "algorithm"),
        Index("ix_training_runs_status", "status"),
        Index("ix_training_runs_started_at", "started_at"),
        Index("ix_training_runs_experiment_status", "experiment_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    experiment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    dataset_version: Mapped[str] = mapped_column(String(length=128), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(length=128), nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    metrics: Mapped[dict[str, float]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    status: Mapped[TrainingRunStatus] = mapped_column(
        SQLAlchemyEnum(
            TrainingRunStatus,
            values_callable=_training_run_status_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
        default=TrainingRunStatus.PENDING,
        server_default=TrainingRunStatus.PENDING.value,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    experiment: Mapped[Experiment] = relationship(
        "Experiment",
        back_populates="training_runs",
    )
    model_artifacts: Mapped[list[ModelArtifact]] = relationship(
        "ModelArtifact",
        back_populates="training_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ModelArtifact(Base):
    """Registered model artifact metadata for a training run."""

    __tablename__ = "model_artifacts"
    __table_args__ = (
        CheckConstraint(
            "length(checksum) = 64",
            name="ck_model_artifacts_checksum_sha256",
        ),
        Index("ix_model_artifacts_training_run_id", "training_run_id"),
        Index("ix_model_artifacts_framework", "framework"),
        Index("ix_model_artifacts_model_type", "model_type"),
        Index("ix_model_artifacts_version", "version"),
        Index("ix_model_artifacts_artifact_path", "artifact_path", unique=True),
        Index(
            "ix_model_artifacts_training_run_version",
            "training_run_id",
            "version",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    training_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("training_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    framework: Mapped[str] = mapped_column(String(length=128), nullable=False)
    model_type: Mapped[str] = mapped_column(String(length=128), nullable=False)
    version: Mapped[str] = mapped_column(String(length=128), nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(length=1024), nullable=False)
    checksum: Mapped[str] = mapped_column(String(length=64), nullable=False)

    training_run: Mapped[TrainingRun] = relationship(
        "TrainingRun",
        back_populates="model_artifacts",
    )
