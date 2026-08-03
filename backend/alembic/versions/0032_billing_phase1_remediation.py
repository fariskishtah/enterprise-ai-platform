"""Add platform billing authority and recoverable webhook delivery state.

Revision ID: 0032_billing_phase1_remediation
Revises: 0031_entitlement_overrides

The downgrade is intended only for a pre-traffic migration rollback. Once the
new recovery metadata is populated, roll back the application while retaining
this forward-compatible schema so webhook and audit evidence is not discarded.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_billing_phase1_remediation"
down_revision: str | None = "0031_entitlement_overrides"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "is_platform_operator",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    op.create_index(
        "ix_subscriptions_lifecycle_due",
        "subscriptions",
        [
            "status",
            "current_period_end",
            "grace_period_ends_at",
            "status_changed_at",
        ],
    )

    op.execute(
        sa.text(
            "UPDATE billing_webhook_events SET status = 'quarantined' "
            "WHERE status = 'ignored'"
        )
    )

    with op.batch_alter_table("billing_webhook_events") as batch:
        batch.add_column(sa.Column("queued_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("processing_started_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("next_retry_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("last_error_category", sa.String(64)))
        batch.add_column(sa.Column("dead_lettered_at", sa.DateTime(timezone=True)))
        batch.add_column(
            sa.Column(
                "replay_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.create_check_constraint(
            "ck_billing_webhook_attempts_nonnegative", "attempts >= 0"
        )
        batch.create_check_constraint(
            "ck_billing_webhook_replay_count_nonnegative", "replay_count >= 0"
        )
        batch.create_check_constraint(
            "ck_billing_webhook_status",
            "status IN ('received','queued','processing','processed','failed',"
            "'dead_letter','quarantined')",
        )
        batch.create_index(
            "ix_billing_webhook_recovery",
            ["status", "next_retry_at", "queued_at", "processing_started_at"],
        )

    op.execute(
        sa.text(
            "UPDATE billing_webhook_events SET queued_at = received_at "
            "WHERE status = 'queued' AND queued_at IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE billing_webhook_events SET processing_started_at = received_at "
            "WHERE status = 'processing' AND processing_started_at IS NULL"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("billing_webhook_events") as batch:
        batch.drop_index("ix_billing_webhook_recovery")
        batch.drop_constraint("ck_billing_webhook_status", type_="check")
        batch.drop_constraint(
            "ck_billing_webhook_replay_count_nonnegative", type_="check"
        )
        batch.drop_constraint("ck_billing_webhook_attempts_nonnegative", type_="check")
        batch.drop_column("replay_count")
        batch.drop_column("dead_lettered_at")
        batch.drop_column("last_error_category")
        batch.drop_column("next_retry_at")
        batch.drop_column("processing_started_at")
        batch.drop_column("queued_at")

    op.execute(
        sa.text(
            "UPDATE billing_webhook_events SET status = 'ignored' "
            "WHERE status = 'quarantined'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE billing_webhook_events SET status = 'failed' "
            "WHERE status = 'dead_letter'"
        )
    )

    with op.batch_alter_table("users") as batch:
        batch.drop_column("is_platform_operator")

    op.drop_index("ix_subscriptions_lifecycle_due", table_name="subscriptions")
