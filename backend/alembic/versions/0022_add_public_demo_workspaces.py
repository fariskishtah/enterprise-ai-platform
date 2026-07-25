"""Mark isolated public-demo company workspaces.

Revision ID: 0022_add_public_demo_workspaces
Revises: 0021_add_support_requests
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_add_public_demo_workspaces"
down_revision: str | None = "0021_add_support_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "is_public_demo",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_companies_public_demo",
        "companies",
        ["is_public_demo"],
    )


def downgrade() -> None:
    op.drop_index("ix_companies_public_demo", table_name="companies")
    op.drop_column("companies", "is_public_demo")
