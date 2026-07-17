"""Sensor data platform ORM models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SQLAlchemyEnum
from sqlalchemy.types import Uuid

from app.db.base import Base
from app.models.sensor import Sensor
from app.models.user import User


class ReadingQuality(StrEnum):
    """Quality flags stored with each sensor reading."""

    GOOD = "GOOD"
    BAD = "BAD"
    MISSING = "MISSING"
    OUTLIER = "OUTLIER"


class ReadingSource(StrEnum):
    """Supported sensor reading sources."""

    CSV = "CSV"
    API = "API"
    SIMULATION = "SIMULATION"


class UploadJobStatus(StrEnum):
    """Upload job lifecycle states."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def _quality_values(enum_type: type[ReadingQuality]) -> list[str]:
    """Return persisted reading quality enum values."""
    return [quality.value for quality in enum_type]


def _source_values(enum_type: type[ReadingSource]) -> list[str]:
    """Return persisted reading source enum values."""
    return [source.value for source in enum_type]


def _status_values(enum_type: type[UploadJobStatus]) -> list[str]:
    """Return persisted upload job status enum values."""
    return [status.value for status in enum_type]


class UploadJob(Base):
    """Sensor data upload job metadata."""

    __tablename__ = "upload_jobs"
    __table_args__ = (
        CheckConstraint(
            "source IN ('CSV', 'API', 'SIMULATION')",
            name="ck_upload_jobs_source_valid",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="ck_upload_jobs_status_valid",
        ),
        CheckConstraint(
            "total_rows >= 0 AND valid_rows >= 0 AND invalid_rows >= 0",
            name="ck_upload_jobs_row_counts_non_negative",
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="ck_upload_jobs_finished_after_started",
        ),
        Index("ix_upload_jobs_created_by", "created_by"),
        Index("ix_upload_jobs_status", "status"),
        Index("ix_upload_jobs_source", "source"),
        Index("ix_upload_jobs_created_at", "created_at"),
        Index("ix_upload_jobs_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    filename: Mapped[str] = mapped_column(String(length=255), nullable=False)
    source: Mapped[ReadingSource] = mapped_column(
        SQLAlchemyEnum(
            ReadingSource,
            values_callable=_source_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    status: Mapped[UploadJobStatus] = mapped_column(
        SQLAlchemyEnum(
            UploadJobStatus,
            values_callable=_status_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
        default=UploadJobStatus.PENDING,
        server_default=UploadJobStatus.PENDING.value,
    )
    total_rows: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    valid_rows: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    invalid_rows: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    readings: Mapped[list[SensorReading]] = relationship(
        "SensorReading",
        back_populates="upload_job",
    )


class SensorReading(Base):
    """Single point-in-time reading emitted by a sensor."""

    __tablename__ = "sensor_readings"
    __table_args__ = (
        CheckConstraint(
            "quality IN ('GOOD', 'BAD', 'MISSING', 'OUTLIER')",
            name="ck_sensor_readings_quality_valid",
        ),
        CheckConstraint(
            "source IN ('CSV', 'API', 'SIMULATION')",
            name="ck_sensor_readings_source_valid",
        ),
        Index("ix_sensor_readings_sensor_id", "sensor_id"),
        Index("ix_sensor_readings_timestamp", "timestamp"),
        Index("ix_sensor_readings_batch_id", "batch_id"),
        Index("ix_sensor_readings_quality", "quality"),
        Index("ix_sensor_readings_source", "source"),
        Index("ix_sensor_readings_created_at", "created_at"),
        Index("ix_sensor_readings_sensor_timestamp", "sensor_id", "timestamp"),
        Index("ix_sensor_readings_batch_timestamp", "batch_id", "timestamp"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    sensor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sensors.id", ondelete="RESTRICT"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    quality: Mapped[ReadingQuality] = mapped_column(
        SQLAlchemyEnum(
            ReadingQuality,
            values_callable=_quality_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    source: Mapped[ReadingSource] = mapped_column(
        SQLAlchemyEnum(
            ReadingSource,
            values_callable=_source_values,
            native_enum=False,
            create_constraint=False,
            length=32,
        ),
        nullable=False,
    )
    batch_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("upload_jobs.id", ondelete="RESTRICT"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    sensor: Mapped[Sensor] = relationship("Sensor", back_populates="readings")
    upload_job: Mapped[UploadJob | None] = relationship(
        "UploadJob",
        back_populates="readings",
    )
