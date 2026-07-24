"""Add company-scoped operational actions, notes, feedback, and timeline.

Revision ID: 0016_add_operational_actions
Revises: 0015_add_pilot_identity_audit
Create Date: 2026-07-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_add_operational_actions"
down_revision: str | None = "0015_add_pilot_identity_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

priority = sa.Enum(
    "critical",
    "high",
    "medium",
    "low",
    name="operationalactionpriority",
    native_enum=False,
    create_constraint=True,
    length=16,
)
action_status = sa.Enum(
    "open",
    "assigned",
    "in_progress",
    "blocked",
    "completed",
    "cancelled",
    name="operationalactionstatus",
    native_enum=False,
    create_constraint=True,
    length=24,
)
note_kind = sa.Enum(
    "operator",
    "engineer",
    name="operationalnotekind",
    native_enum=False,
    create_constraint=True,
    length=16,
)
feedback_outcome = sa.Enum(
    "true_issue",
    "false_alarm",
    "sensor_fault",
    "maintenance_performed",
    "no_action_required",
    "machine_stopped",
    "other",
    name="maintenancefeedbackoutcome",
    native_enum=False,
    create_constraint=True,
    length=32,
)


def upgrade() -> None:
    op.create_table(
        "operational_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("factory_id", sa.Uuid(), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("related_alert_id", sa.Uuid()),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("priority", priority, nullable=False),
        sa.Column(
            "status",
            action_status,
            server_default="open",
            nullable=False,
        ),
        sa.Column("assigned_user_id", sa.Uuid()),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("completion_summary", sa.Text()),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("version > 0", name="ck_operational_actions_version"),
        sa.ForeignKeyConstraint(
            ["assigned_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["related_alert_id"], ["monitoring_alerts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_operational_actions_company_status",
        "operational_actions",
        ["company_id", "status"],
    )
    op.create_index(
        "ix_operational_actions_factory_status",
        "operational_actions",
        ["factory_id", "status"],
    )
    op.create_index(
        "ix_operational_actions_machine_status",
        "operational_actions",
        ["machine_id", "status"],
    )
    op.create_index(
        "ix_operational_actions_assignee_status",
        "operational_actions",
        ["assigned_user_id", "status"],
    )
    op.create_index(
        "ix_operational_actions_priority_due",
        "operational_actions",
        ["priority", "due_at"],
    )
    op.create_index(
        "ix_operational_actions_company_created",
        "operational_actions",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_operational_actions_company_title",
        "operational_actions",
        ["company_id", "title"],
    )

    op.create_table(
        "operational_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("factory_id", sa.Uuid(), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Uuid()),
        sa.Column("alert_id", sa.Uuid()),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", note_kind, nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(action_id IS NOT NULL AND alert_id IS NULL) OR "
            "(action_id IS NULL AND alert_id IS NOT NULL)",
            name="ck_operational_note_one_parent",
        ),
        sa.ForeignKeyConstraint(
            ["action_id"], ["operational_actions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"], ["monitoring_alerts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_operational_notes_company_created",
        "operational_notes",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_operational_notes_action_created",
        "operational_notes",
        ["action_id", "created_at"],
    )
    op.create_index(
        "ix_operational_notes_alert_created",
        "operational_notes",
        ["alert_id", "created_at"],
    )

    op.create_table(
        "maintenance_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("factory_id", sa.Uuid(), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Uuid()),
        sa.Column("alert_id", sa.Uuid()),
        sa.Column("outcome", feedback_outcome, nullable=False),
        sa.Column("maintenance_category", sa.String(128)),
        sa.Column("replaced_component", sa.String(128)),
        sa.Column("downtime_minutes", sa.Integer()),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("submitted_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action_id IS NOT NULL OR alert_id IS NOT NULL",
            name="ck_maintenance_feedback_parent",
        ),
        sa.CheckConstraint(
            "downtime_minutes IS NULL OR downtime_minutes >= 0",
            name="ck_maintenance_feedback_downtime",
        ),
        sa.ForeignKeyConstraint(
            ["action_id"], ["operational_actions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"], ["monitoring_alerts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["submitted_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_maintenance_feedback_company_created",
        "maintenance_feedback",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_maintenance_feedback_machine_created",
        "maintenance_feedback",
        ["machine_id", "created_at"],
    )
    op.create_index(
        "ix_maintenance_feedback_outcome_created",
        "maintenance_feedback",
        ["outcome", "created_at"],
    )

    op.create_table(
        "operational_timeline_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("factory_id", sa.Uuid(), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Uuid()),
        sa.Column("alert_id", sa.Uuid()),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("safe_metadata", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["action_id"], ["operational_actions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["alert_id"], ["monitoring_alerts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_operational_timeline_machine_time",
        "operational_timeline_events",
        ["machine_id", "occurred_at", "id"],
    )
    op.create_index(
        "ix_operational_timeline_company_time",
        "operational_timeline_events",
        ["company_id", "occurred_at", "id"],
    )
    op.create_index(
        "ix_operational_timeline_factory_time",
        "operational_timeline_events",
        ["factory_id", "occurred_at", "id"],
    )
    op.create_index(
        "ix_operational_timeline_event_time",
        "operational_timeline_events",
        ["event_type", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("operational_timeline_events")
    op.drop_table("maintenance_feedback")
    op.drop_table("operational_notes")
    op.drop_table("operational_actions")
