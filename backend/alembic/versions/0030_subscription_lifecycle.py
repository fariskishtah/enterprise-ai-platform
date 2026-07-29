"""Add production subscription lifecycle persistence.

Revision ID: 0030_subscription_lifecycle
Revises: 0029_harden_payment_events
"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision: str = "0030_subscription_lifecycle"
down_revision: str | None = "0029_harden_payment_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PLANS = (
    ("0d1bfb31-7e64-5fd6-a303-93fb8d58af22", "starter", "Starter", 100_000),
    ("20f51597-dff7-5411-bfe3-af965d479e0b", "professional", "Professional", 500_000),
    ("6ca74490-ae1f-5f84-9139-e6aa738557ab", "enterprise", "Enterprise", 1_000_000),
)

_ENTITLEMENTS: dict[str, dict[str, int | bool]] = {
    "starter": {
        "team_members": 5,
        "factories": 1,
        "machines": 25,
        "document_storage_gb": 2,
        "monthly_rag_queries": 500,
        "model_training": False,
        "training_concurrency": 0,
        "advanced_reports": False,
        "scheduled_reports": 0,
        "audit_log": False,
    },
    "professional": {
        "team_members": 25,
        "factories": 5,
        "machines": 250,
        "document_storage_gb": 25,
        "monthly_rag_queries": 5_000,
        "model_training": True,
        "training_concurrency": 2,
        "advanced_reports": True,
        "scheduled_reports": 10,
        "audit_log": False,
    },
    "enterprise": {
        "team_members": 100,
        "factories": 25,
        "machines": 2_000,
        "document_storage_gb": 250,
        "monthly_rag_queries": 50_000,
        "model_training": True,
        "training_concurrency": 10,
        "advanced_reports": True,
        "scheduled_reports": 100,
        "audit_log": True,
    },
}


def upgrade() -> None:
    connection = op.get_bind()
    for plan_id, code, name, price in _PLANS:
        connection.execute(
            sa.text(
                "INSERT INTO billing_plans "
                "(id, code, name, currency, monthly_price_minor, is_active) "
                "VALUES (:id, :code, :name, 'EGP', :price, true) "
                "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, "
                "monthly_price_minor = EXCLUDED.monthly_price_minor, "
                "currency = EXCLUDED.currency, is_active = true"
            ),
            {"id": plan_id, "code": code, "name": name, "price": price},
        )
        resolved_id = connection.execute(
            sa.text("SELECT id FROM billing_plans WHERE code = :code"), {"code": code}
        ).scalar_one()
        for key, value in _ENTITLEMENTS[code].items():
            connection.execute(
                sa.text(
                    "INSERT INTO plan_entitlements "
                    "(id, plan_id, key, integer_limit, enabled) "
                    "VALUES (:id, :plan_id, :key, :integer_limit, :enabled) "
                    "ON CONFLICT (plan_id, key) DO UPDATE SET "
                    "integer_limit = EXCLUDED.integer_limit, enabled = EXCLUDED.enabled"
                ),
                {
                    "id": str(uuid5(NAMESPACE_URL, f"billing:{code}:{key}")),
                    "plan_id": resolved_id,
                    "key": key,
                    "integer_limit": (
                        value
                        if isinstance(value, int) and not isinstance(value, bool)
                        else None
                    ),
                    "enabled": value if isinstance(value, bool) else None,
                },
            )

    with op.batch_alter_table("subscriptions") as batch:
        batch.add_column(sa.Column("pending_plan_id", sa.Uuid()))
        batch.add_column(sa.Column("latest_payment_id", sa.Uuid()))
        batch.add_column(
            sa.Column(
                "status_changed_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )
        batch.add_column(sa.Column("suspended_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("ended_at", sa.DateTime(timezone=True)))
        batch.add_column(
            sa.Column("version", sa.Integer(), server_default="1", nullable=False)
        )
        batch.create_foreign_key(
            "fk_subscriptions_pending_plan",
            "billing_plans",
            ["pending_plan_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_unique_constraint("uq_subscriptions_company", ["company_id"])

    with op.batch_alter_table("payments") as batch:
        batch.add_column(
            sa.Column(
                "purpose", sa.String(32), server_default="initial", nullable=False
            )
        )

    with op.batch_alter_table("subscriptions") as batch:
        batch.create_foreign_key(
            "fk_subscriptions_latest_payment",
            "payments",
            ["latest_payment_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("invoice_references") as batch:
        batch.add_column(sa.Column("payment_id", sa.Uuid()))
        batch.create_foreign_key(
            "fk_invoice_references_payment",
            "payments",
            ["payment_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint("uq_invoice_references_payment", ["payment_id"])

    with op.batch_alter_table("billing_webhook_events") as batch:
        batch.add_column(sa.Column("company_id", sa.Uuid()))
        batch.create_foreign_key(
            "fk_billing_webhook_company",
            "companies",
            ["company_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_billing_webhook_events_company_id", ["company_id"])


def downgrade() -> None:
    with op.batch_alter_table("billing_webhook_events") as batch:
        batch.drop_index("ix_billing_webhook_events_company_id")
        batch.drop_constraint("fk_billing_webhook_company", type_="foreignkey")
        batch.drop_column("company_id")
    with op.batch_alter_table("invoice_references") as batch:
        batch.drop_constraint("uq_invoice_references_payment", type_="unique")
        batch.drop_constraint("fk_invoice_references_payment", type_="foreignkey")
        batch.drop_column("payment_id")
    with op.batch_alter_table("subscriptions") as batch:
        batch.drop_constraint("fk_subscriptions_latest_payment", type_="foreignkey")
    with op.batch_alter_table("payments") as batch:
        batch.drop_column("purpose")
    with op.batch_alter_table("subscriptions") as batch:
        batch.drop_constraint("uq_subscriptions_company", type_="unique")
        batch.drop_constraint("fk_subscriptions_pending_plan", type_="foreignkey")
        batch.drop_column("version")
        batch.drop_column("ended_at")
        batch.drop_column("suspended_at")
        batch.drop_column("status_changed_at")
        batch.drop_column("latest_payment_id")
        batch.drop_column("pending_plan_id")
