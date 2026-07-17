"""Create manufacturing domain tables.

Revision ID: 0002_create_manufacturing_domain
Revises: 0001_create_users_and_refresh_tokens
Create Date: 2026-07-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_create_manufacturing_domain"
down_revision: str | None = "0001_create_users_and_refresh_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_companies_normalized_name",
        "companies",
        ["normalized_name"],
        unique=True,
    )
    op.create_index("ix_companies_name", "companies", ["name"])
    op.create_index("ix_companies_deleted_at", "companies", ["deleted_at"])

    op.create_table(
        "factories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_factories_company_id", "factories", ["company_id"])
    op.create_index("ix_factories_name", "factories", ["name"])
    op.create_index("ix_factories_deleted_at", "factories", ["deleted_at"])
    op.create_index(
        "ix_factories_company_deleted",
        "factories",
        ["company_id", "deleted_at"],
    )

    op.create_table(
        "machines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("factory_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("serial_number", sa.String(length=255), nullable=True),
        sa.Column("manufacturer", sa.String(length=255), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_machines_factory_id", "machines", ["factory_id"])
    op.create_index("ix_machines_name", "machines", ["name"])
    op.create_index("ix_machines_serial_number", "machines", ["serial_number"])
    op.create_index("ix_machines_deleted_at", "machines", ["deleted_at"])
    op.create_index(
        "ix_machines_factory_deleted",
        "machines",
        ["factory_id", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_machines_factory_deleted", table_name="machines")
    op.drop_index("ix_machines_deleted_at", table_name="machines")
    op.drop_index("ix_machines_serial_number", table_name="machines")
    op.drop_index("ix_machines_name", table_name="machines")
    op.drop_index("ix_machines_factory_id", table_name="machines")
    op.drop_table("machines")
    op.drop_index("ix_factories_company_deleted", table_name="factories")
    op.drop_index("ix_factories_deleted_at", table_name="factories")
    op.drop_index("ix_factories_name", table_name="factories")
    op.drop_index("ix_factories_company_id", table_name="factories")
    op.drop_table("factories")
    op.drop_index("ix_companies_deleted_at", table_name="companies")
    op.drop_index("ix_companies_name", table_name="companies")
    op.drop_index("ix_companies_normalized_name", table_name="companies")
    op.drop_table("companies")
