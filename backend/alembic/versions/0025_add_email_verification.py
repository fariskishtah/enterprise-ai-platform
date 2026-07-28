"""Add email verification lifecycle and encrypted outbound payloads.

Revision ID: 0025_add_email_verification
Revises: 0024_add_transactional_email
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_add_email_verification"
down_revision: str | None = "0024_add_transactional_email"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    op.execute(
        sa.text(
            "UPDATE users SET email_verified_at = CURRENT_TIMESTAMP "
            "WHERE is_email_verified = true"
        )
    )
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "is_email_verified",
            existing_type=sa.Boolean(),
            server_default=sa.false(),
            existing_nullable=False,
        )

    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_email_verification_tokens_hash",
        "email_verification_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_email_verification_tokens_user_created",
        "email_verification_tokens",
        ["user_id", "created_at"],
    )
    op.add_column(
        "outbound_email_messages",
        sa.Column(
            "payload_encrypted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("outbound_email_messages", "payload_encrypted")
    op.drop_index(
        "ix_email_verification_tokens_user_created",
        table_name="email_verification_tokens",
    )
    op.drop_index(
        "ix_email_verification_tokens_hash",
        table_name="email_verification_tokens",
    )
    op.drop_table("email_verification_tokens")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("email_verified_at")
        batch_op.drop_column("is_email_verified")
