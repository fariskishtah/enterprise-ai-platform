"""Add refresh-token family lineage for replay containment.

Revision ID: 0028_add_refresh_token_families
Revises: 0027_add_team_invitations
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_add_refresh_token_families"
down_revision: str | None = "0027_add_team_invitations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("refresh_tokens") as batch:
        batch.add_column(sa.Column("family_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("parent_token_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_refresh_tokens_parent_token_id",
            "refresh_tokens",
            ["parent_token_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.execute(sa.text("UPDATE refresh_tokens SET family_id = id"))
    with op.batch_alter_table("refresh_tokens") as batch:
        batch.alter_column("family_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_index("ix_refresh_tokens_family_id", ["family_id"])


def downgrade() -> None:
    with op.batch_alter_table("refresh_tokens") as batch:
        batch.drop_index("ix_refresh_tokens_family_id")
        batch.drop_constraint("fk_refresh_tokens_parent_token_id", type_="foreignkey")
        batch.drop_column("parent_token_id")
        batch.drop_column("family_id")
