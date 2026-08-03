"""Add browser, provider-decision, intent, and reconciliation contracts.

Revision ID: 0033_billing_phase2_contracts
Revises: 0032_billing_phase1_remediation

The downgrade is permitted only before payment traffic exists. Operational
rollback after traffic is an application rollback that retains this evidence.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033_billing_phase2_contracts"
down_revision: str | None = "0032_billing_phase1_remediation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("payments") as batch:
        batch.add_column(
            sa.Column(
                "checkout_intent_status",
                sa.String(32),
                nullable=False,
                server_default="open",
            )
        )
        batch.add_column(sa.Column("checkout_expires_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("superseded_by_payment_id", sa.Uuid()))
        batch.add_column(sa.Column("return_reference_hash", sa.String(64)))
        batch.add_column(
            sa.Column("return_reference_expires_at", sa.DateTime(timezone=True))
        )
        batch.add_column(sa.Column("return_reference_purpose", sa.String(32)))
        batch.add_column(
            sa.Column(
                "environment",
                sa.String(16),
                nullable=False,
                server_default="legacy_unknown",
            )
        )
        batch.add_column(
            sa.Column(
                "commercial_model",
                sa.String(48),
                nullable=False,
                server_default="prepaid_manual_renewal",
            )
        )
        batch.add_column(
            sa.Column(
                "provider_decision",
                sa.String(32),
                nullable=False,
                server_default="pending",
            )
        )
        batch.add_column(sa.Column("provider_integration_id", sa.Integer()))
        batch.add_column(sa.Column("provider_merchant_id", sa.String(128)))
        batch.add_column(sa.Column("provider_order_id", sa.String(255)))
        batch.create_foreign_key(
            "fk_payments_superseded_by_payment_id",
            "payments",
            ["superseded_by_payment_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "ck_payments_checkout_intent_status",
            "checkout_intent_status IN "
            "('open','superseded','completed','failed','expired','cancelled')",
        )
        batch.create_check_constraint(
            "ck_payments_environment",
            "environment IN ('sandbox','live','legacy_unknown')",
        )
        batch.create_check_constraint(
            "ck_payments_commercial_model",
            "commercial_model IN "
            "('prepaid_manual_renewal','provider_recurring_subscription')",
        )
        batch.create_check_constraint(
            "ck_payments_provider_decision",
            "provider_decision IN "
            "('pending','authorized_not_captured','succeeded_eligible','failed',"
            "'cancelled','expired','refunded','reversed','under_review','quarantined')",
        )
        batch.create_index(
            "ix_payments_return_reference_hash",
            ["return_reference_hash"],
            unique=True,
        )
        batch.create_index(
            "ix_payments_checkout_expiry",
            ["checkout_intent_status", "checkout_expires_at"],
        )

    op.execute(
        sa.text(
            "UPDATE payments SET checkout_intent_status = CASE "
            "WHEN status = 'succeeded' THEN 'completed' "
            "WHEN status = 'failed' THEN 'failed' "
            "WHEN status = 'cancelled' THEN 'cancelled' "
            "WHEN status IN ('refunded','reversed') THEN 'completed' "
            "WHEN status = 'provider_error' THEN 'open' ELSE 'open' END, "
            "provider_decision = CASE "
            "WHEN status = 'succeeded' THEN 'succeeded_eligible' "
            "WHEN status = 'failed' THEN 'failed' "
            "WHEN status = 'cancelled' THEN 'cancelled' "
            "WHEN status = 'refunded' THEN 'refunded' "
            "WHEN status = 'reversed' THEN 'reversed' ELSE 'pending' END"
        )
    )
    op.execute(
        sa.text(
            "UPDATE payments SET checkout_intent_status = 'superseded', "
            "superseded_by_payment_id = ("
            "SELECT newest.id FROM payments AS newest "
            "WHERE newest.company_id = payments.company_id "
            "AND newest.checkout_intent_status = 'open' "
            "ORDER BY newest.created_at DESC, newest.id DESC LIMIT 1) "
            "WHERE checkout_intent_status = 'open' AND id <> ("
            "SELECT newest.id FROM payments AS newest "
            "WHERE newest.company_id = payments.company_id "
            "AND newest.checkout_intent_status = 'open' "
            "ORDER BY newest.created_at DESC, newest.id DESC LIMIT 1)"
        )
    )
    op.create_index(
        "uq_payments_company_open_intent",
        "payments",
        ["company_id"],
        unique=True,
        postgresql_where=sa.text("checkout_intent_status = 'open'"),
        sqlite_where=sa.text("checkout_intent_status = 'open'"),
    )

    with op.batch_alter_table("billing_webhook_events") as batch:
        batch.add_column(
            sa.Column(
                "validation_outcome",
                sa.String(64),
                nullable=False,
                server_default="accepted",
            )
        )

    op.create_table(
        "billing_reconciliation_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column(
            "triggered_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("finance_approval_reference", sa.String(128)),
        sa.Column("summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "provider",
            "environment",
            "idempotency_key",
            name="uq_billing_reconciliation_run_key",
        ),
        sa.CheckConstraint(
            "status IN ('running','completed','failed')",
            name="ck_billing_reconciliation_run_status",
        ),
        sa.CheckConstraint(
            "environment IN ('sandbox','live')",
            name="ck_billing_reconciliation_run_environment",
        ),
    )
    op.create_index(
        "ix_billing_reconciliation_runs_time",
        "billing_reconciliation_runs",
        ["started_at", "status"],
    )

    op.create_table(
        "billing_reconciliation_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("billing_reconciliation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "company_id", sa.Uuid(), sa.ForeignKey("companies.id", ondelete="SET NULL")
        ),
        sa.Column(
            "payment_id", sa.Uuid(), sa.ForeignKey("payments.id", ondelete="SET NULL")
        ),
        sa.Column("provider_payment_id", sa.String(255)),
        sa.Column("outcome", sa.String(48), nullable=False),
        sa.Column("local_state", sa.String(32)),
        sa.Column("provider_state", sa.String(32)),
        sa.Column("safe_details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "compensating_event_id",
            sa.Uuid(),
            sa.ForeignKey("billing_webhook_events.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "outcome IN "
            "('matched','provider_missing','local_missing','amount_mismatch',"
            "'currency_mismatch','integration_mismatch','environment_mismatch',"
            "'state_mismatch','manual_review_required','corrected_by_compensating_event')",
            name="ck_billing_reconciliation_result_outcome",
        ),
    )
    op.create_index(
        "ix_billing_reconciliation_results_run",
        "billing_reconciliation_results",
        ["run_id", "outcome"],
    )
    op.create_index(
        "ix_billing_reconciliation_results_company",
        "billing_reconciliation_results",
        ["company_id", "created_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    payment_count = connection.execute(
        sa.text("SELECT count(*) FROM payments")
    ).scalar()
    result_count = connection.execute(
        sa.text("SELECT count(*) FROM billing_reconciliation_results")
    ).scalar()
    reconciliation_run_count = connection.execute(
        sa.text("SELECT count(*) FROM billing_reconciliation_runs")
    ).scalar()
    webhook_event_count = connection.execute(
        sa.text("SELECT count(*) FROM billing_webhook_events")
    ).scalar()
    if payment_count or result_count or reconciliation_run_count or webhook_event_count:
        raise RuntimeError(
            "Billing evidence exists; use application rollback and retain 0033."
        )

    op.drop_index(
        "ix_billing_reconciliation_results_company",
        table_name="billing_reconciliation_results",
    )
    op.drop_index(
        "ix_billing_reconciliation_results_run",
        table_name="billing_reconciliation_results",
    )
    op.drop_table("billing_reconciliation_results")
    op.drop_index(
        "ix_billing_reconciliation_runs_time", table_name="billing_reconciliation_runs"
    )
    op.drop_table("billing_reconciliation_runs")
    with op.batch_alter_table("billing_webhook_events") as batch:
        batch.drop_column("validation_outcome")
    op.drop_index("uq_payments_company_open_intent", table_name="payments")
    with op.batch_alter_table("payments") as batch:
        batch.drop_index("ix_payments_checkout_expiry")
        batch.drop_index("ix_payments_return_reference_hash")
        batch.drop_constraint("ck_payments_provider_decision", type_="check")
        batch.drop_constraint("ck_payments_commercial_model", type_="check")
        batch.drop_constraint("ck_payments_environment", type_="check")
        batch.drop_constraint("ck_payments_checkout_intent_status", type_="check")
        batch.drop_constraint(
            "fk_payments_superseded_by_payment_id", type_="foreignkey"
        )
        batch.drop_column("provider_order_id")
        batch.drop_column("provider_merchant_id")
        batch.drop_column("provider_integration_id")
        batch.drop_column("provider_decision")
        batch.drop_column("commercial_model")
        batch.drop_column("environment")
        batch.drop_column("return_reference_purpose")
        batch.drop_column("return_reference_expires_at")
        batch.drop_column("return_reference_hash")
        batch.drop_column("superseded_by_payment_id")
        batch.drop_column("checkout_expires_at")
        batch.drop_column("checkout_intent_status")
