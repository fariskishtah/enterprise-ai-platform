"""Add executive report jobs and bounded schedules.

Revision ID: 0020_add_executive_reports
Revises: 0019_add_demo_scenarios_and_layouts
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_add_executive_reports"
down_revision: str | None = "0019_add_demo_scenarios_and_layouts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("factory_id", sa.Uuid()),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("report_type", sa.String(48), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("storage_key", sa.String(64)),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("sha256_digest", sa.String(64)),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("safe_error", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_report_job_company_idempotency",
        "report_jobs",
        ["company_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_report_job_company_created", "report_jobs", ["company_id", "created_at"]
    )
    op.create_index(
        "ix_report_job_company_status", "report_jobs", ["company_id", "status"]
    )
    op.create_table(
        "report_schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("factory_id", sa.Uuid()),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("report_type", sa.String(48), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("cadence", sa.String(16), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("recipients", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_result", sa.String(32)),
        sa.Column("last_error", sa.Text()),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_report_schedule_company_idempotency",
        "report_schedules",
        ["company_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_report_schedule_company_enabled",
        "report_schedules",
        ["company_id", "enabled"],
    )
    op.create_index("ix_report_schedule_next_run", "report_schedules", ["next_run_at"])


def downgrade() -> None:
    op.drop_table("report_schedules")
    op.drop_table("report_jobs")
