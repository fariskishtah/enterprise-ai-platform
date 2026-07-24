"""Add enhanced alert lifecycle and shift handover.

Revision ID: 0017_add_alert_shift_workflow
Revises: 0016_add_operational_actions
Create Date: 2026-07-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_add_alert_shift_workflow"
down_revision: str | None = "0016_add_operational_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

shift_status = sa.Enum(
    "active",
    "ended",
    "acknowledged",
    name="shiftstatus",
    native_enum=False,
    create_constraint=True,
    length=16,
)


def upgrade() -> None:
    with op.batch_alter_table("monitoring_alerts") as batch:
        batch.add_column(sa.Column("assigned_user_id", sa.Uuid()))
        batch.add_column(sa.Column("assigned_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("assigned_by_user_id", sa.Uuid()))
        batch.add_column(sa.Column("in_progress_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("escalated_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("escalated_by_user_id", sa.Uuid()))
        batch.add_column(sa.Column("resolution_summary", sa.Text()))
        batch.add_column(sa.Column("resolution_classification", sa.String(32)))
        batch.add_column(sa.Column("reopened_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("reopened_by_user_id", sa.Uuid()))
        batch.add_column(sa.Column("reopen_reason", sa.Text()))
        batch.add_column(
            sa.Column(
                "lifecycle_version",
                sa.Integer(),
                server_default="1",
                nullable=False,
            )
        )
        batch.create_foreign_key(
            "fk_monitoring_alerts_assigned_user_id",
            "users",
            ["assigned_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_monitoring_alerts_assigned_by_user_id",
            "users",
            ["assigned_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_monitoring_alerts_escalated_by_user_id",
            "users",
            ["escalated_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_monitoring_alerts_reopened_by_user_id",
            "users",
            ["reopened_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_monitoring_alert_assignee_status",
            ["assigned_user_id", "status"],
        )
        batch.create_index(
            "ix_monitoring_alert_company_title",
            ["company_id", "title"],
        )

    op.create_table(
        "shift_handovers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("factory_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            shift_status,
            server_default="active",
            nullable=False,
        ),
        sa.Column("started_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("ended_by_user_id", sa.Uuid()),
        sa.Column("acknowledged_by_user_id", sa.Uuid()),
        sa.Column("team_label", sa.String(128)),
        sa.Column("handover_notes", sa.Text()),
        sa.Column("unresolved_summary", sa.Text()),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
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
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["started_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["ended_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["acknowledged_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_shift_handovers_company_status",
        "shift_handovers",
        ["company_id", "status"],
    )
    op.create_index(
        "ix_shift_handovers_factory_status",
        "shift_handovers",
        ["factory_id", "status"],
    )
    op.create_index(
        "ix_shift_handovers_factory_started",
        "shift_handovers",
        ["factory_id", "started_at"],
    )
    op.create_index(
        "uq_shift_handovers_active_factory",
        "shift_handovers",
        ["factory_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_table("shift_handovers")
    with op.batch_alter_table("monitoring_alerts") as batch:
        batch.drop_index("ix_monitoring_alert_company_title")
        batch.drop_index("ix_monitoring_alert_assignee_status")
        batch.drop_constraint(
            "fk_monitoring_alerts_reopened_by_user_id", type_="foreignkey"
        )
        batch.drop_constraint(
            "fk_monitoring_alerts_escalated_by_user_id", type_="foreignkey"
        )
        batch.drop_constraint(
            "fk_monitoring_alerts_assigned_by_user_id", type_="foreignkey"
        )
        batch.drop_constraint(
            "fk_monitoring_alerts_assigned_user_id", type_="foreignkey"
        )
        batch.drop_column("lifecycle_version")
        batch.drop_column("reopen_reason")
        batch.drop_column("reopened_by_user_id")
        batch.drop_column("reopened_at")
        batch.drop_column("resolution_classification")
        batch.drop_column("resolution_summary")
        batch.drop_column("escalated_by_user_id")
        batch.drop_column("escalated_at")
        batch.drop_column("in_progress_at")
        batch.drop_column("assigned_by_user_id")
        batch.drop_column("assigned_at")
        batch.drop_column("assigned_user_id")
