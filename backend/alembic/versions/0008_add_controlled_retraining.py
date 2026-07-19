"""Add controlled retraining policies, requests, and evaluation audits.

Revision ID: 0008_add_controlled_retraining
Revises: 0007_add_ai_prediction_monitoring
Create Date: 2026-07-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_add_controlled_retraining"
down_revision: str | None = "0007_add_ai_prediction_monitoring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_retraining_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("registered_model_name", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("allowed_trigger_types", sa.JSON(), nullable=False),
        sa.Column("minimum_drift_status", sa.String(32), nullable=False),
        sa.Column("minimum_current_sample_count", sa.Integer(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("maximum_requests_per_day", sa.Integer(), nullable=False),
        sa.Column("maximum_requests_per_week", sa.Integer(), nullable=False),
        sa.Column("maximum_active_requests", sa.Integer(), nullable=False),
        sa.Column("require_champion_source", sa.Boolean(), nullable=False),
        sa.Column("allow_truncated_drift", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "cooldown_seconds >= 0", name="ck_retraining_policy_cooldown"
        ),
        sa.CheckConstraint(
            "minimum_drift_status IN ('warning', 'critical')",
            name="ck_retraining_policy_drift_status",
        ),
        sa.CheckConstraint(
            "minimum_current_sample_count > 0 AND maximum_requests_per_day > 0 "
            "AND maximum_requests_per_week > 0 AND maximum_active_requests > 0",
            name="ck_retraining_policy_positive_limits",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "registered_model_name", name="uq_retraining_policy_model_name"
        ),
    )
    op.create_index(
        "ix_retraining_policy_enabled", "model_retraining_policies", ["enabled"]
    )

    op.create_table(
        "model_retraining_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("registered_model_name", sa.String(128), nullable=False),
        sa.Column("source_model_version", sa.String(128), nullable=False),
        sa.Column("source_training_job_id", sa.Uuid(), nullable=False),
        sa.Column("algorithm", sa.String(32), nullable=False),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("trigger_reference", sa.String(512), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("decision_status", sa.String(48), nullable=False),
        sa.Column("request_status", sa.String(32), nullable=False),
        sa.Column("evaluation_mode", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("training_job_id", sa.Uuid(), nullable=True),
        sa.Column("resulting_model_version", sa.String(128), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("override_used", sa.Boolean(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_failure_code", sa.String(64), nullable=True),
        sa.Column("safe_failure_message", sa.Text(), nullable=True),
        sa.Column("comparison", sa.JSON(), nullable=True),
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
        sa.CheckConstraint(
            "trigger_type IN ('feature_drift', 'prediction_drift', "
            "'data_quality', 'manual')",
            name="ck_retraining_request_trigger_type",
        ),
        sa.CheckConstraint(
            "decision_status IN ('eligible', 'not_eligible', "
            "'blocked_cooldown', 'blocked_duplicate', 'blocked_quota', "
            "'blocked_insufficient_data', 'blocked_missing_profile', "
            "'blocked_missing_training_evidence', 'disabled')",
            name="ck_retraining_request_decision_status",
        ),
        sa.CheckConstraint(
            "request_status IN ('pending', 'submitted', 'training', "
            "'candidate_created', 'completed', 'failed', 'cancelled')",
            name="ck_retraining_request_status",
        ),
        sa.CheckConstraint(
            "evaluation_mode IN ('automatic', 'manual')",
            name="ck_retraining_request_mode",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"], ["model_retraining_policies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_training_job_id"], ["training_jobs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["training_job_id"], ["training_jobs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_retraining_request_idempotency"
        ),
        sa.UniqueConstraint(
            "training_job_id", name="uq_retraining_request_training_job"
        ),
    )
    op.create_index(
        "ix_retraining_request_model_status",
        "model_retraining_requests",
        ["registered_model_name", "request_status"],
    )
    op.create_index(
        "ix_retraining_request_requested_at",
        "model_retraining_requests",
        ["requested_at"],
    )
    op.create_index(
        "ix_retraining_request_policy", "model_retraining_requests", ["policy_id"]
    )

    op.create_table(
        "model_retraining_audits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("registered_model_name", sa.String(128), nullable=False),
        sa.Column("source_model_version", sa.String(128), nullable=True),
        sa.Column("requested_alias", sa.String(128), nullable=True),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("trigger_reference", sa.String(512), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("decision_status", sa.String(48), nullable=False),
        sa.Column("decision_reasons", sa.JSON(), nullable=False),
        sa.Column("drift_summary", sa.JSON(), nullable=False),
        sa.Column("thresholds", sa.JSON(), nullable=False),
        sa.Column("cooldown_state", sa.JSON(), nullable=False),
        sa.Column("quota_state", sa.JSON(), nullable=False),
        sa.Column("existing_request_id", sa.Uuid(), nullable=True),
        sa.Column("created_request_id", sa.Uuid(), nullable=True),
        sa.Column("evaluated_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_mode", sa.String(32), nullable=False),
        sa.Column("override_used", sa.Boolean(), nullable=False),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "trigger_type IN ('feature_drift', 'prediction_drift', "
            "'data_quality', 'manual')",
            name="ck_retraining_audit_trigger_type",
        ),
        sa.CheckConstraint(
            "decision_status IN ('eligible', 'not_eligible', "
            "'blocked_cooldown', 'blocked_duplicate', 'blocked_quota', "
            "'blocked_insufficient_data', 'blocked_missing_profile', "
            "'blocked_missing_training_evidence', 'disabled')",
            name="ck_retraining_audit_decision_status",
        ),
        sa.CheckConstraint(
            "evaluation_mode IN ('automatic', 'manual')",
            name="ck_retraining_audit_mode",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"], ["model_retraining_policies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["evaluated_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["existing_request_id"],
            ["model_retraining_requests.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_request_id"],
            ["model_retraining_requests.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_retraining_audit_model",
        "model_retraining_audits",
        ["registered_model_name"],
    )
    op.create_index(
        "ix_retraining_audit_evaluated_at",
        "model_retraining_audits",
        ["evaluated_at"],
    )
    op.create_index(
        "ix_retraining_audit_evaluator",
        "model_retraining_audits",
        ["evaluated_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_retraining_audit_evaluator", table_name="model_retraining_audits")
    op.drop_index(
        "ix_retraining_audit_evaluated_at", table_name="model_retraining_audits"
    )
    op.drop_index("ix_retraining_audit_model", table_name="model_retraining_audits")
    op.drop_table("model_retraining_audits")
    op.drop_index(
        "ix_retraining_request_policy", table_name="model_retraining_requests"
    )
    op.drop_index(
        "ix_retraining_request_requested_at", table_name="model_retraining_requests"
    )
    op.drop_index(
        "ix_retraining_request_model_status", table_name="model_retraining_requests"
    )
    op.drop_table("model_retraining_requests")
    op.drop_index(
        "ix_retraining_policy_enabled", table_name="model_retraining_policies"
    )
    op.drop_table("model_retraining_policies")
