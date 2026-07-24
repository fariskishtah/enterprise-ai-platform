"""Add deterministic demo scenarios and 2D factory layouts.

Revision ID: 0019_add_demo_scenarios_and_layouts
Revises: 0018_add_guided_data_imports
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_add_demo_scenarios_and_layouts"
down_revision: str | None = "0018_add_guided_data_imports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "factory_layouts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("factory_id", sa.Uuid(), nullable=False),
        sa.Column("nodes", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_factory_layout_factory", "factory_layouts", ["factory_id"], unique=True
    )
    op.create_index("ix_factory_layout_company", "factory_layouts", ["company_id"])
    op.create_table(
        "demo_scenario_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("factory_id", sa.Uuid(), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("scenario", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("speed", sa.Integer(), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False),
        sa.Column("generated_readings", sa.Integer(), nullable=False),
        sa.Column("state_snapshot", sa.JSON(), nullable=False),
        sa.Column("generated_resources", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("stopped_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_demo_scenario_company_idempotency",
        "demo_scenario_runs",
        ["company_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_demo_scenario_machine_status",
        "demo_scenario_runs",
        ["machine_id", "status"],
    )
    op.create_index(
        "ix_demo_scenario_company_started",
        "demo_scenario_runs",
        ["company_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_table("demo_scenario_runs")
    op.drop_table("factory_layouts")
