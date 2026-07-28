"""Add tenant billing and usage persistence foundation.

Revision ID: 0023_add_billing_foundation
Revises: 0022_add_public_demo_workspaces
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_add_billing_foundation"
down_revision: str | None = "0022_add_public_demo_workspaces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column:
    return sa.Column("id", sa.Uuid(), primary_key=True)


def _created() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "billing_plans",
        _id(),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("monthly_price_minor", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _created(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "monthly_price_minor > 0", name="ck_billing_plans_positive_price"
        ),
        sa.CheckConstraint("currency = 'EGP'", name="ck_billing_plans_egp"),
        sa.UniqueConstraint("code", name="uq_billing_plans_code"),
    )
    op.create_table(
        "plan_entitlements",
        _id(),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("billing_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("integer_limit", sa.Integer()),
        sa.Column("enabled", sa.Boolean()),
        sa.CheckConstraint(
            "integer_limit IS NULL OR integer_limit >= 0",
            name="ck_plan_entitlements_nonnegative",
        ),
        sa.CheckConstraint(
            "integer_limit IS NOT NULL OR enabled IS NOT NULL",
            name="ck_plan_entitlements_value",
        ),
        sa.UniqueConstraint("plan_id", "key", name="uq_plan_entitlements_plan_key"),
    )
    op.create_table(
        "payment_provider_customers",
        _id(),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_customer_id", sa.String(255), nullable=False),
        _created(),
        sa.UniqueConstraint(
            "company_id", "provider", name="uq_provider_customer_company_provider"
        ),
        sa.UniqueConstraint(
            "provider", "provider_customer_id", name="uq_provider_customer_external"
        ),
    )
    op.create_index(
        "ix_payment_provider_customers_company_id",
        "payment_provider_customers",
        ["company_id"],
    )
    op.create_table(
        "subscriptions",
        _id(),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("billing_plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "provider_customer_id",
            sa.Uuid(),
            sa.ForeignKey("payment_provider_customers.id", ondelete="SET NULL"),
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_subscription_id", sa.String(255)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True)),
        sa.Column("current_period_end", sa.DateTime(timezone=True)),
        sa.Column("grace_period_ends_at", sa.DateTime(timezone=True)),
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        _created(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('trialing','active','past_due','suspended','cancelled','expired','incomplete')",
            name="ck_subscriptions_status",
        ),
        sa.UniqueConstraint(
            "provider", "provider_subscription_id", name="uq_subscription_external"
        ),
    )
    op.create_index(
        "ix_subscriptions_company_status", "subscriptions", ["company_id", "status"]
    )
    op.create_table(
        "payments",
        _id(),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            sa.Uuid(),
            sa.ForeignKey("subscriptions.id", ondelete="SET NULL"),
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_payment_id", sa.String(255), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("failure_code", sa.String(80)),
        _created(),
        sa.CheckConstraint("amount_minor > 0", name="ck_payments_positive_amount"),
        sa.CheckConstraint("currency = 'EGP'", name="ck_payments_egp"),
        sa.UniqueConstraint(
            "provider", "provider_payment_id", name="uq_payment_external"
        ),
    )
    op.create_index(
        "ix_payments_company_time", "payments", ["company_id", "created_at"]
    )
    op.create_table(
        "invoice_references",
        _id(),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            sa.Uuid(),
            sa.ForeignKey("subscriptions.id", ondelete="SET NULL"),
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_invoice_id", sa.String(255), nullable=False),
        sa.Column("receipt_url", sa.String(1024)),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount_minor > 0", name="ck_invoice_positive_amount"),
        sa.CheckConstraint("currency = 'EGP'", name="ck_invoice_egp"),
        sa.UniqueConstraint(
            "provider", "provider_invoice_id", name="uq_invoice_external"
        ),
    )
    op.create_index(
        "ix_invoice_references_company_id", "invoice_references", ["company_id"]
    )
    op.create_table(
        "billing_webhook_events",
        _id(),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="received"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "provider", "provider_event_id", name="uq_billing_webhook_event"
        ),
    )
    op.create_index(
        "ix_billing_webhook_status", "billing_webhook_events", ["status", "received_at"]
    )
    op.create_table(
        "usage_counters",
        _id(),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_usage_quantity_nonnegative"),
        sa.CheckConstraint("period_end >= period_start", name="ck_usage_period_order"),
        sa.UniqueConstraint(
            "company_id",
            "metric",
            "period_start",
            name="uq_usage_company_metric_period",
        ),
    )
    op.create_index(
        "ix_usage_company_period",
        "usage_counters",
        ["company_id", "period_start", "period_end"],
    )
    op.create_table(
        "billing_audit_events",
        _id(),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("safe_metadata", sa.JSON(), nullable=False),
        _created(),
    )
    op.create_index(
        "ix_billing_audit_company_time",
        "billing_audit_events",
        ["company_id", "created_at"],
    )


def downgrade() -> None:
    for table in (
        "billing_audit_events",
        "usage_counters",
        "billing_webhook_events",
        "invoice_references",
        "payments",
        "subscriptions",
        "payment_provider_customers",
        "plan_entitlements",
        "billing_plans",
    ):
        op.drop_table(table)
