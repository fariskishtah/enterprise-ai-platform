"""Add durable team invitations.

Revision ID: 0027_add_team_invitations
Revises: 0026_add_six_role_rbac
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_add_team_invitations"
down_revision: str | None = "0026_add_six_role_rbac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "team_invitations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("invited_email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "inviter_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "accepted_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("send_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'engineer', 'operator', 'analyst', 'viewer')",
            name="ck_team_invitations_role_valid",
        ),
    )
    op.create_index(
        "ix_team_invitations_token_hash",
        "team_invitations",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_team_invitations_company_created",
        "team_invitations",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_team_invitations_company_email",
        "team_invitations",
        ["company_id", "invited_email"],
    )


def downgrade() -> None:
    op.drop_index("ix_team_invitations_company_email", table_name="team_invitations")
    op.drop_index("ix_team_invitations_company_created", table_name="team_invitations")
    op.drop_index("ix_team_invitations_token_hash", table_name="team_invitations")
    op.drop_table("team_invitations")
