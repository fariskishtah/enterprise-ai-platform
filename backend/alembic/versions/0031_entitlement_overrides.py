"""Add audited tenant entitlement overrides and expanded plan quotas.

Revision ID: 0031_entitlement_overrides
Revises: 0030_subscription_lifecycle
"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision: str = "0031_entitlement_overrides"
down_revision: str | None = "0030_subscription_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entitlement_overrides",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("integer_limit", sa.Integer()),
        sa.Column("enabled", sa.Boolean()),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
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
        sa.CheckConstraint(
            "integer_limit IS NOT NULL OR enabled IS NOT NULL",
            name="ck_entitlement_overrides_value",
        ),
        sa.CheckConstraint(
            "integer_limit IS NULL OR integer_limit >= 0",
            name="ck_entitlement_overrides_nonnegative",
        ),
        sa.UniqueConstraint(
            "company_id", "key", name="uq_entitlement_overrides_company_key"
        ),
    )
    op.create_index(
        "ix_entitlement_overrides_company_expiry",
        "entitlement_overrides",
        ["company_id", "expires_at"],
    )
    op.create_table(
        "usage_ledger_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name="ck_usage_ledger_quantity"),
        sa.UniqueConstraint(
            "company_id",
            "metric",
            "idempotency_key",
            name="uq_usage_ledger_company_metric_key",
        ),
    )
    op.create_index(
        "ix_usage_ledger_company_period",
        "usage_ledger_events",
        ["company_id", "period_start"],
    )
    connection = op.get_bind()
    values = {"starter": 100, "professional": 2_500, "enterprise": 25_000}
    for code, limit in values.items():
        connection.execute(
            sa.text(
                "INSERT INTO plan_entitlements "
                "(id, plan_id, key, integer_limit, enabled) "
                "SELECT :id, id, 'documents', :limit, NULL FROM billing_plans "
                "WHERE code = :code "
                "ON CONFLICT (plan_id, key) DO UPDATE SET "
                "integer_limit = EXCLUDED.integer_limit, enabled = NULL"
            ),
            {
                "id": str(uuid5(NAMESPACE_URL, f"billing:{code}:documents")),
                "code": code,
                "limit": limit,
            },
        )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM plan_entitlements WHERE key = 'documents'"))
    op.drop_table("usage_ledger_events")
    op.drop_table("entitlement_overrides")
