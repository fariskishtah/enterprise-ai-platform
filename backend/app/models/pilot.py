"""Governed model input schemas and operator-facing pilot risk records."""

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
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base


class ModelFeatureSchema(Base):
    """Exact, tenant-owned feature contract for one registered model version."""

    __tablename__ = "model_feature_schemas"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "registered_model_name",
            "model_version",
            name="uq_model_feature_schema_company_version",
        ),
        Index(
            "ix_model_feature_schema_lookup",
            "company_id",
            "registered_model_name",
            "model_version",
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
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    features: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    target_metadata: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    training_dataset_version_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="SET NULL"),
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MachineRiskAssessment(Base):
    """Privacy-bounded risk indication shown in the controlled operator pilot."""

    __tablename__ = "machine_risk_assessments"
    __table_args__ = (
        CheckConstraint(
            "risk_state IN ('normal','observe','warning','critical',"
            "'insufficient_data','model_unavailable')",
            name="ck_machine_risk_state",
        ),
        CheckConstraint(
            "risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 1)",
            name="ck_machine_risk_score",
        ),
        Index("ix_machine_risk_company_time", "company_id", "assessed_at"),
        Index("ix_machine_risk_machine_time", "machine_id", "assessed_at"),
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
    prediction_event_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("prediction_events.id", ondelete="SET NULL"),
    )
    alert_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitoring_alerts.id", ondelete="SET NULL"),
    )
    registered_model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    risk_state: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_score: Mapped[float | None] = mapped_column(Float)
    sensor_values: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    data_freshness_seconds: Mapped[float | None] = mapped_column(Float)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    monitoring_status: Mapped[str] = mapped_column(String(32), nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
