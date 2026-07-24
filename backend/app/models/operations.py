"""Company-scoped operational maintenance workflow entities."""

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
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Enum as SQLAlchemyEnum
from sqlalchemy.types import Uuid

from app.db.base import Base


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [item.value for item in enum_type]


class OperationalActionPriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class OperationalActionStatus(StrEnum):
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class OperationalNoteKind(StrEnum):
    OPERATOR = "operator"
    ENGINEER = "engineer"


class MaintenanceFeedbackOutcome(StrEnum):
    TRUE_ISSUE = "true_issue"
    FALSE_ALARM = "false_alarm"
    SENSOR_FAULT = "sensor_fault"
    MAINTENANCE_PERFORMED = "maintenance_performed"
    NO_ACTION_REQUIRED = "no_action_required"
    MACHINE_STOPPED = "machine_stopped"
    OTHER = "other"


class ShiftStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"
    ACKNOWLEDGED = "acknowledged"


class OperationalAction(Base):
    """Assignable, non-destructive unit of factory work."""

    __tablename__ = "operational_actions"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_operational_actions_version"),
        Index("ix_operational_actions_company_status", "company_id", "status"),
        Index("ix_operational_actions_factory_status", "factory_id", "status"),
        Index("ix_operational_actions_machine_status", "machine_id", "status"),
        Index("ix_operational_actions_assignee_status", "assigned_user_id", "status"),
        Index("ix_operational_actions_priority_due", "priority", "due_at"),
        Index("ix_operational_actions_company_created", "company_id", "created_at"),
        Index("ix_operational_actions_company_title", "company_id", "title"),
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
    related_alert_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitoring_alerts.id", ondelete="SET NULL"),
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[OperationalActionPriority] = mapped_column(
        SQLAlchemyEnum(
            OperationalActionPriority,
            name="operationalactionpriority",
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            length=16,
        ),
        nullable=False,
    )
    status: Mapped[OperationalActionStatus] = mapped_column(
        SQLAlchemyEnum(
            OperationalActionStatus,
            name="operationalactionstatus",
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            length=24,
        ),
        nullable=False,
        default=OperationalActionStatus.OPEN,
        server_default=OperationalActionStatus.OPEN.value,
    )
    assigned_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completion_summary: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
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


class OperationalNote(Base):
    """Append-only operator or engineer note on an action or alert."""

    __tablename__ = "operational_notes"
    __table_args__ = (
        CheckConstraint(
            "(action_id IS NOT NULL AND alert_id IS NULL) OR "
            "(action_id IS NULL AND alert_id IS NOT NULL)",
            name="ck_operational_note_one_parent",
        ),
        Index("ix_operational_notes_company_created", "company_id", "created_at"),
        Index("ix_operational_notes_action_created", "action_id", "created_at"),
        Index("ix_operational_notes_alert_created", "alert_id", "created_at"),
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
    action_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("operational_actions.id", ondelete="RESTRICT"),
    )
    alert_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitoring_alerts.id", ondelete="RESTRICT"),
    )
    author_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[OperationalNoteKind] = mapped_column(
        SQLAlchemyEnum(
            OperationalNoteKind,
            name="operationalnotekind",
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            length=16,
        ),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MaintenanceFeedback(Base):
    """Immutable human interpretation of an operational outcome."""

    __tablename__ = "maintenance_feedback"
    __table_args__ = (
        CheckConstraint(
            "action_id IS NOT NULL OR alert_id IS NOT NULL",
            name="ck_maintenance_feedback_parent",
        ),
        CheckConstraint(
            "downtime_minutes IS NULL OR downtime_minutes >= 0",
            name="ck_maintenance_feedback_downtime",
        ),
        Index("ix_maintenance_feedback_company_created", "company_id", "created_at"),
        Index("ix_maintenance_feedback_machine_created", "machine_id", "created_at"),
        Index("ix_maintenance_feedback_outcome_created", "outcome", "created_at"),
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
    action_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("operational_actions.id", ondelete="RESTRICT"),
    )
    alert_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitoring_alerts.id", ondelete="RESTRICT"),
    )
    outcome: Mapped[MaintenanceFeedbackOutcome] = mapped_column(
        SQLAlchemyEnum(
            MaintenanceFeedbackOutcome,
            name="maintenancefeedbackoutcome",
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            length=32,
        ),
        nullable=False,
    )
    maintenance_category: Mapped[str | None] = mapped_column(String(128))
    replaced_component: Mapped[str | None] = mapped_column(String(128))
    downtime_minutes: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OperationalTimelineEvent(Base):
    """Role-safe operational history distinct from security audit history."""

    __tablename__ = "operational_timeline_events"
    __table_args__ = (
        Index(
            "ix_operational_timeline_machine_time",
            "machine_id",
            "occurred_at",
            "id",
        ),
        Index(
            "ix_operational_timeline_company_time", "company_id", "occurred_at", "id"
        ),
        Index(
            "ix_operational_timeline_factory_time", "factory_id", "occurred_at", "id"
        ),
        Index("ix_operational_timeline_event_time", "event_type", "occurred_at"),
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
    action_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("operational_actions.id", ondelete="SET NULL"),
    )
    alert_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitoring_alerts.id", ondelete="SET NULL"),
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    safe_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ShiftHandover(Base):
    """Lightweight factory shift and handover context."""

    __tablename__ = "shift_handovers"
    __table_args__ = (
        Index("ix_shift_handovers_company_status", "company_id", "status"),
        Index("ix_shift_handovers_factory_status", "factory_id", "status"),
        Index("ix_shift_handovers_factory_started", "factory_id", "started_at"),
        Index(
            "uq_shift_handovers_active_factory",
            "factory_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
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
    factory_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("factories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[ShiftStatus] = mapped_column(
        SQLAlchemyEnum(
            ShiftStatus,
            name="shiftstatus",
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            length=16,
        ),
        nullable=False,
        default=ShiftStatus.ACTIVE,
        server_default=ShiftStatus.ACTIVE.value,
    )
    started_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    ended_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    acknowledged_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    team_label: Mapped[str | None] = mapped_column(String(128))
    handover_notes: Mapped[str | None] = mapped_column(Text)
    unresolved_summary: Mapped[str | None] = mapped_column(Text)
    snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
