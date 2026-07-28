"""Add the six-role tenant authorization model.

Revision ID: 0026_add_six_role_rbac
Revises: 0025_add_email_verification
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_add_six_role_rbac"
down_revision: str | None = "0025_add_email_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_role_valid", type_="check")
        batch_op.create_check_constraint(
            "ck_users_role_valid",
            "role IN ('owner', 'admin', 'engineer', 'operator', 'analyst', 'viewer')",
        )
    op.execute(sa.text("UPDATE users SET role = 'owner' WHERE role = 'admin'"))


def downgrade() -> None:
    op.execute(sa.text("UPDATE users SET role = 'admin' WHERE role = 'owner'"))
    op.execute(
        sa.text(
            "UPDATE users SET role = 'operator' WHERE role IN ('analyst', 'viewer')"
        )
    )
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_role_valid", type_="check")
        batch_op.create_check_constraint(
            "ck_users_role_valid",
            "role IN ('admin', 'engineer', 'operator')",
        )
