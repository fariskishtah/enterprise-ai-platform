"""Add persistent AI training jobs and promotion audits.

Revision ID: 0006_add_ai_jobs_and_promotion
Revises: 0005_create_mlops_foundation
Create Date: 2026-07-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_add_ai_jobs_and_promotion"
down_revision: str | None = "0005_create_mlops_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "training_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("specification", sa.JSON(), nullable=False),
        sa.Column("experiment_name", sa.String(length=255), nullable=False),
        sa.Column("run_name", sa.String(length=255), nullable=True),
        sa.Column("registered_model_name", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("queue_message_id", sa.String(length=255), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("safe_error_message", sa.Text(), nullable=True),
        sa.Column("local_execution_run_id", sa.Uuid(), nullable=True),
        sa.Column("mlflow_experiment_id", sa.String(length=255), nullable=True),
        sa.Column("mlflow_run_id", sa.String(length=255), nullable=True),
        sa.Column("registered_model_version", sa.String(length=128), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_training_jobs_status_valid",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts",
            name="ck_training_jobs_attempts_valid",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_training_jobs_state_version_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "requested_by_user_id",
            "algorithm",
            "task_type",
            "idempotency_key",
            name="uq_training_jobs_scoped_idempotency",
        ),
    )
    op.create_index(
        "ix_training_jobs_requested_by_user_id",
        "training_jobs",
        ["requested_by_user_id"],
    )
    op.create_index("ix_training_jobs_status", "training_jobs", ["status"])
    op.create_index("ix_training_jobs_created_at", "training_jobs", ["created_at"])
    op.create_index(
        "ix_training_jobs_status_started_at",
        "training_jobs",
        ["status", "started_at"],
    )
    op.create_index(
        "ix_training_jobs_model_version",
        "training_jobs",
        ["registered_model_name", "registered_model_version"],
    )
    op.create_index(
        "ix_training_jobs_queue_message_id",
        "training_jobs",
        ["queue_message_id"],
        unique=True,
    )

    op.create_table(
        "model_promotion_audits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("registered_model_name", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column(
            "action",
            sa.String(length=64),
            server_default="assign_alias",
            nullable=False,
        ),
        sa.Column("target_alias", sa.String(length=32), nullable=False),
        sa.Column("previous_version", sa.String(length=128), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("policy_result", sa.JSON(), nullable=False),
        sa.Column("force", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "operation_outcome",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("safe_error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "action = 'assign_alias'",
            name="ck_model_promotion_audits_action_valid",
        ),
        sa.CheckConstraint(
            "target_alias IN ('challenger', 'champion')",
            name="ck_model_promotion_audits_alias_valid",
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected', 'overridden')",
            name="ck_model_promotion_audits_decision_valid",
        ),
        sa.CheckConstraint(
            "operation_outcome IN ('pending', 'succeeded', 'failed')",
            name="ck_model_promotion_audits_outcome_valid",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_model_promotion_audits_model_name",
        "model_promotion_audits",
        ["registered_model_name"],
    )
    op.create_index(
        "ix_model_promotion_audits_requested_by",
        "model_promotion_audits",
        ["requested_by_user_id"],
    )
    op.create_index(
        "ix_model_promotion_audits_created_at",
        "model_promotion_audits",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_promotion_audits_created_at",
        table_name="model_promotion_audits",
    )
    op.drop_index(
        "ix_model_promotion_audits_requested_by",
        table_name="model_promotion_audits",
    )
    op.drop_index(
        "ix_model_promotion_audits_model_name",
        table_name="model_promotion_audits",
    )
    op.drop_table("model_promotion_audits")
    op.drop_index("ix_training_jobs_queue_message_id", table_name="training_jobs")
    op.drop_index("ix_training_jobs_model_version", table_name="training_jobs")
    op.drop_index("ix_training_jobs_status_started_at", table_name="training_jobs")
    op.drop_index("ix_training_jobs_created_at", table_name="training_jobs")
    op.drop_index("ix_training_jobs_status", table_name="training_jobs")
    op.drop_index("ix_training_jobs_requested_by_user_id", table_name="training_jobs")
    op.drop_table("training_jobs")
