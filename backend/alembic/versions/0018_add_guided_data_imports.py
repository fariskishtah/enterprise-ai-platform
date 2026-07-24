"""Add company-scoped guided data imports.

Revision ID: 0018_add_guided_data_imports
Revises: 0017_add_alert_shift_workflow
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_add_guided_data_imports"
down_revision: str | None = "0017_add_alert_shift_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("storage_key", sa.String(64), nullable=False),
        sa.Column("sha256_digest", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("delimiter", sa.String(1), nullable=False),
        sa.Column("has_header", sa.Boolean(), nullable=False),
        sa.Column("mapping", sa.JSON(), nullable=False),
        sa.Column("preview", sa.JSON(), nullable=False),
        sa.Column("quality_report", sa.JSON(), nullable=False),
        sa.Column("error_samples", sa.JSON(), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("imported_rows", sa.Integer(), nullable=False),
        sa.Column("rejected_rows", sa.Integer(), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("warnings_accepted", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_data_import_company_idempotency",
        "data_imports",
        ["company_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_data_import_company_created", "data_imports", ["company_id", "created_at"]
    )
    op.create_index(
        "ix_data_import_company_status", "data_imports", ["company_id", "status"]
    )


def downgrade() -> None:
    op.drop_table("data_imports")
