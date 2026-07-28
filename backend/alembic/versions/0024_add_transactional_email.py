"""Add durable transactional email delivery state.

Revision ID: 0024_add_transactional_email
Revises: 0023_add_billing_foundation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_add_transactional_email"
down_revision: str | None = "0023_add_billing_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbound_email_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
        ),
        sa.Column("message_type", sa.String(48), nullable=False),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("from_address", sa.String(320), nullable=False),
        sa.Column("from_name", sa.String(100), nullable=False),
        sa.Column("reply_to", sa.String(320)),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("text_body", sa.Text(), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_message_id", sa.String(255)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(255)),
        sa.Column("deduplication_key", sa.String(255), nullable=False),
        sa.Column("related_resource_type", sa.String(64)),
        sa.Column("related_resource_id", sa.Uuid()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "message_type IN ('email_verification','password_reset','welcome',"
            "'team_invitation','feedback_received','support_request_received',"
            "'subscription_confirmation','payment_confirmation','payment_failure',"
            "'subscription_cancellation')",
            name="ck_outbound_email_message_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued','processing','retrying','captured','sent','failed')",
            name="ck_outbound_email_status",
        ),
        sa.CheckConstraint(
            "retry_count >= 0 AND retry_count <= max_retries",
            name="ck_outbound_email_retry_bound",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= max_retries + 1",
            name="ck_outbound_email_attempt_bound",
        ),
        sa.CheckConstraint(
            "max_retries >= 1 AND max_retries <= 10",
            name="ck_outbound_email_max_retries",
        ),
        sa.UniqueConstraint(
            "deduplication_key", name="uq_outbound_email_deduplication_key"
        ),
    )
    op.create_index(
        "ix_outbound_email_status_next",
        "outbound_email_messages",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_outbound_email_company_created",
        "outbound_email_messages",
        ["company_id", "created_at"],
    )
    with op.batch_alter_table("support_requests") as batch_op:
        batch_op.drop_constraint("ck_support_requests_delivery_attempts", type_="check")
        batch_op.create_check_constraint(
            "ck_support_requests_delivery_attempts",
            "delivery_attempts >= 0 AND delivery_attempts <= 11",
        )


def downgrade() -> None:
    with op.batch_alter_table("support_requests") as batch_op:
        batch_op.drop_constraint("ck_support_requests_delivery_attempts", type_="check")
        batch_op.create_check_constraint(
            "ck_support_requests_delivery_attempts",
            "delivery_attempts >= 0 AND delivery_attempts <= 5",
        )
    op.drop_index(
        "ix_outbound_email_company_created",
        table_name="outbound_email_messages",
    )
    op.drop_index("ix_outbound_email_status_next", table_name="outbound_email_messages")
    op.drop_table("outbound_email_messages")
