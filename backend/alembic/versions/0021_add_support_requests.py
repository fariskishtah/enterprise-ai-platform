"""Add optional user names and company support request delivery state.

Revision ID: 0021_add_support_requests
Revises: 0020_add_executive_reports
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_add_support_requests"
down_revision: str | None = "0020_add_executive_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.String(160)))
    op.create_table(
        "support_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("factory_id", sa.Uuid()),
        sa.Column("machine_id", sa.Uuid()),
        sa.Column("requester_name", sa.String(160), nullable=False),
        sa.Column("requester_email", sa.String(320), nullable=False),
        sa.Column("requester_role", sa.String(32), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(160), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("current_page", sa.String(500), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("provider_message_id", sa.String(255)),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(255)),
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
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('submitted', 'delivered', 'delivery_failed', 'closed')",
            name="ck_support_requests_status",
        ),
        sa.CheckConstraint(
            "delivery_attempts >= 0 AND delivery_attempts <= 5",
            name="ck_support_requests_delivery_attempts",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_support_request_actor_idempotency",
        "support_requests",
        ["company_id", "created_by", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_support_request_company_created",
        "support_requests",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_support_request_company_status",
        "support_requests",
        ["company_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("support_requests")
    op.drop_column("users", "full_name")
