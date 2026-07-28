"""Harden checkout and webhook persistence for provider processing.

Revision ID: 0029_harden_payment_events
Revises: 0028_add_refresh_token_families
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_harden_payment_events"
down_revision: str | None = "0028_add_refresh_token_families"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("payments") as batch:
        batch.alter_column(
            "provider_payment_id",
            existing_type=sa.String(255),
            nullable=True,
        )
        batch.add_column(sa.Column("provider_checkout_id", sa.String(255)))
        batch.add_column(sa.Column("idempotency_key", sa.String(128)))
        batch.add_column(sa.Column("plan_code", sa.String(32)))
        batch.add_column(sa.Column("checkout_url", sa.String(2048)))
        batch.add_column(sa.Column("provider_occurred_at", sa.DateTime(timezone=True)))
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )
        batch.create_unique_constraint(
            "uq_payment_checkout_external", ["provider", "provider_checkout_id"]
        )
        batch.create_unique_constraint(
            "uq_payment_company_idempotency", ["company_id", "idempotency_key"]
        )
        batch.create_check_constraint(
            "ck_payments_status",
            "status IN ('creating','pending','succeeded','failed','cancelled',"
            "'refunded','reversed','provider_error')",
        )

    with op.batch_alter_table("billing_webhook_events") as batch:
        batch.add_column(sa.Column("raw_provider_event_id", sa.String(255)))
        batch.add_column(sa.Column("safe_payload", sa.JSON()))


def downgrade() -> None:
    with op.batch_alter_table("billing_webhook_events") as batch:
        batch.drop_column("safe_payload")
        batch.drop_column("raw_provider_event_id")

    op.execute(
        sa.text(
            "UPDATE payments SET provider_payment_id = "
            "'checkout:' || CAST(id AS VARCHAR) "
            "WHERE provider_payment_id IS NULL"
        )
    )
    with op.batch_alter_table("payments") as batch:
        batch.drop_constraint("ck_payments_status", type_="check")
        batch.drop_constraint("uq_payment_company_idempotency", type_="unique")
        batch.drop_constraint("uq_payment_checkout_external", type_="unique")
        batch.drop_column("updated_at")
        batch.drop_column("provider_occurred_at")
        batch.drop_column("checkout_url")
        batch.drop_column("plan_code")
        batch.drop_column("idempotency_key")
        batch.drop_column("provider_checkout_id")
        batch.alter_column(
            "provider_payment_id",
            existing_type=sa.String(255),
            nullable=False,
        )
