"""Company-scoped guided onboarding, demo, and reporting entities."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base


class DataImportStatus(StrEnum):
    QUEUED = "queued"
    VALIDATING = "validating"
    IMPORTING = "importing"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DemoScenarioStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"


class ReportStatus(StrEnum):
    QUEUED = "queued"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class DataImport(Base):
    """A safely stored CSV moving through explicit guided-import states."""

    __tablename__ = "data_imports"
    __table_args__ = (
        Index(
            "uq_data_import_company_idempotency",
            "company_id",
            "idempotency_key",
            unique=True,
        ),
        Index("ix_data_import_company_created", "company_id", "created_at"),
        Index("ix_data_import_company_status", "company_id", "status"),
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
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(64), nullable=False)
    sha256_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DataImportStatus.QUEUED.value
    )
    delimiter: Mapped[str] = mapped_column(String(1), nullable=False, default=",")
    has_header: Mapped[bool] = mapped_column(nullable=False, default=True)
    mapping: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    preview: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    quality_report: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    error_samples: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings_accepted: Mapped[bool] = mapped_column(nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class FactoryLayout(Base):
    """Small 2D layout containing positions for existing factory machines."""

    __tablename__ = "factory_layouts"
    __table_args__ = (
        Index("uq_factory_layout_factory", "factory_id", unique=True),
        Index("ix_factory_layout_company", "company_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    factory_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("factories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    nodes: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DemoScenarioRun(Base):
    """Persisted state for one bounded deterministic machine scenario."""

    __tablename__ = "demo_scenario_runs"
    __table_args__ = (
        Index(
            "uq_demo_scenario_company_idempotency",
            "company_id",
            "idempotency_key",
            unique=True,
        ),
        Index("ix_demo_scenario_machine_status", "machine_id", "status"),
        Index("ix_demo_scenario_company_started", "company_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    factory_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("factories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("machines.id", ondelete="RESTRICT"),
        nullable=False,
    )
    scenario: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    speed: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_readings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    generated_resources: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReportJob(Base):
    """Authorized generated report metadata and bounded payload snapshot."""

    __tablename__ = "report_jobs"
    __table_args__ = (
        Index(
            "uq_report_job_company_idempotency",
            "company_id",
            "idempotency_key",
            unique=True,
        ),
        Index("ix_report_job_company_created", "company_id", "created_at"),
        Index("ix_report_job_company_status", "company_id", "status"),
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
        Uuid(as_uuid=True), ForeignKey("factories.id", ondelete="RESTRICT")
    )
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    report_type: Mapped[str] = mapped_column(String(48), nullable=False)
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256_digest: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    safe_error: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReportSchedule(Base):
    """Bounded company report delivery configuration."""

    __tablename__ = "report_schedules"
    __table_args__ = (
        Index(
            "uq_report_schedule_company_idempotency",
            "company_id",
            "idempotency_key",
            unique=True,
        ),
        Index("ix_report_schedule_company_enabled", "company_id", "enabled"),
        Index("ix_report_schedule_next_run", "next_run_at"),
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
        Uuid(as_uuid=True), ForeignKey("factories.id", ondelete="RESTRICT")
    )
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    report_type: Mapped[str] = mapped_column(String(48), nullable=False)
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    cadence: Mapped[str] = mapped_column(String(16), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    recipients: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_result: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
