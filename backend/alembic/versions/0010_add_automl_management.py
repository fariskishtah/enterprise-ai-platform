"""Add AutoML study, trial, and execution-slot persistence.

Revision ID: 0010_add_automl_management
Revises: 0009_add_monitoring_orchestration
Create Date: 2026-07-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_add_automl_management"
down_revision: str | None = "0009_add_monitoring_orchestration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "automl_studies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="queued", nullable=False),
        sa.Column("primary_metric", sa.String(64), nullable=False),
        sa.Column("metric_direction", sa.String(16), nullable=False),
        sa.Column(
            "sampler_type", sa.String(16), server_default="random", nullable=False
        ),
        sa.Column("random_seed", sa.Integer(), nullable=False),
        sa.Column("plugin_ids", sa.JSON(), nullable=False),
        sa.Column("search_spaces", sa.JSON(), nullable=False),
        sa.Column("preprocessing", sa.JSON(), nullable=False),
        sa.Column("data_specification", sa.JSON(), nullable=False),
        sa.Column("cross_validation_folds", sa.Integer(), nullable=False),
        sa.Column("trial_budget", sa.Integer(), nullable=False),
        sa.Column("time_budget_seconds", sa.Integer(), nullable=False),
        sa.Column("per_trial_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_concurrent_trials", sa.Integer(), nullable=False),
        sa.Column(
            "register_champion", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("registered_model_name", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("queue_message_id", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("best_trial_id", sa.Uuid(), nullable=True),
        sa.Column("champion_training_job_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("safe_error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_automl_studies_status",
        ),
        sa.CheckConstraint(
            "task_type IN ('classification','regression')",
            name="ck_automl_studies_task",
        ),
        sa.CheckConstraint(
            "metric_direction IN ('maximize','minimize')",
            name="ck_automl_studies_direction",
        ),
        sa.CheckConstraint("sampler_type = 'random'", name="ck_automl_studies_sampler"),
        sa.CheckConstraint(
            "trial_budget BETWEEN 1 AND 100", name="ck_automl_studies_trial_budget"
        ),
        sa.CheckConstraint(
            "cross_validation_folds BETWEEN 2 AND 10", name="ck_automl_studies_cv_folds"
        ),
        sa.CheckConstraint(
            "time_budget_seconds BETWEEN 60 AND 86400",
            name="ck_automl_studies_time_budget",
        ),
        sa.CheckConstraint(
            "per_trial_timeout_seconds BETWEEN 10 AND 21600 AND "
            "per_trial_timeout_seconds <= time_budget_seconds",
            name="ck_automl_studies_trial_timeout",
        ),
        sa.CheckConstraint(
            "max_concurrent_trials BETWEEN 1 AND 4 AND "
            "max_concurrent_trials <= trial_budget",
            name="ck_automl_studies_concurrency",
        ),
        sa.CheckConstraint(
            "state_version >= 0", name="ck_automl_studies_state_version"
        ),
        sa.CheckConstraint(
            "register_champion = false OR registered_model_name IS NOT NULL",
            name="ck_automl_studies_champion_name",
        ),
        sa.CheckConstraint(
            "registered_model_name IS NULL OR "
            "length(registered_model_name) BETWEEN 3 AND 128",
            name="ck_automl_studies_model_name_length",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["champion_training_job_id"], ["training_jobs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "requested_by_user_id",
            "idempotency_key",
            name="uq_automl_studies_scoped_idempotency",
        ),
    )
    op.create_index(
        "ix_automl_studies_requester_created",
        "automl_studies",
        ["requested_by_user_id", "created_at"],
    )
    op.create_index(
        "ix_automl_studies_status_created", "automl_studies", ["status", "created_at"]
    )
    op.create_index(
        "ix_automl_studies_task_created", "automl_studies", ["task_type", "created_at"]
    )
    op.create_index(
        "ix_automl_studies_reconciliation", "automl_studies", ["status", "deadline_at"]
    )

    op.create_table(
        "automl_trials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("trial_number", sa.Integer(), nullable=False),
        sa.Column("plugin_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="queued", nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("parameter_fingerprint", sa.String(64), nullable=False),
        sa.Column("random_seed", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("queue_message_id", sa.String(255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fold_metrics", sa.JSON(), nullable=True),
        sa.Column("aggregate_metrics", sa.JSON(), nullable=True),
        sa.Column("primary_metric_value", sa.Float(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("safe_error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','pruned','cancelled')",
            name="ck_automl_trials_status",
        ),
        sa.CheckConstraint("trial_number >= 0", name="ck_automl_trials_number"),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 10 AND "
            "attempt_count <= max_attempts",
            name="ck_automl_trials_attempts",
        ),
        sa.CheckConstraint("state_version >= 0", name="ck_automl_trials_state_version"),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_automl_trials_duration",
        ),
        sa.CheckConstraint(
            "primary_metric_value IS NULL OR "
            "primary_metric_value BETWEEN -1e308 AND 1e308",
            name="ck_automl_trials_metric_finite",
        ),
        sa.ForeignKeyConstraint(
            ["study_id"], ["automl_studies.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "study_id", "trial_number", name="uq_automl_trials_study_number"
        ),
        sa.UniqueConstraint(
            "study_id",
            "parameter_fingerprint",
            name="uq_automl_trials_study_fingerprint",
        ),
    )
    op.create_index(
        "ix_automl_trials_study_status", "automl_trials", ["study_id", "status"]
    )
    op.create_index(
        "ix_automl_trials_study_plugin", "automl_trials", ["study_id", "plugin_id"]
    )
    op.create_index(
        "ix_automl_trials_study_metric",
        "automl_trials",
        ["study_id", "primary_metric_value"],
    )
    op.create_index("ix_automl_trials_lease", "automl_trials", ["lease_expires_at"])
    op.create_index(
        "ix_automl_trials_queue_message", "automl_trials", ["queue_message_id"]
    )

    with op.batch_alter_table("automl_studies") as batch:
        batch.create_foreign_key(
            "fk_automl_studies_best_trial",
            "automl_trials",
            ["best_trial_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "automl_execution_slots",
        sa.Column("slot_number", sa.Integer(), nullable=False),
        sa.Column("trial_id", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("slot_number > 0", name="ck_automl_slots_number"),
        sa.CheckConstraint("state_version >= 0", name="ck_automl_slots_state_version"),
        sa.ForeignKeyConstraint(
            ["trial_id"], ["automl_trials.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("slot_number"),
        sa.UniqueConstraint("trial_id", name="uq_automl_slots_trial"),
    )


def downgrade() -> None:
    op.drop_table("automl_execution_slots")
    with op.batch_alter_table("automl_studies") as batch:
        batch.drop_constraint("fk_automl_studies_best_trial", type_="foreignkey")
    op.drop_index("ix_automl_trials_queue_message", table_name="automl_trials")
    op.drop_index("ix_automl_trials_lease", table_name="automl_trials")
    op.drop_index("ix_automl_trials_study_metric", table_name="automl_trials")
    op.drop_index("ix_automl_trials_study_plugin", table_name="automl_trials")
    op.drop_index("ix_automl_trials_study_status", table_name="automl_trials")
    op.drop_table("automl_trials")
    op.drop_index("ix_automl_studies_reconciliation", table_name="automl_studies")
    op.drop_index("ix_automl_studies_task_created", table_name="automl_studies")
    op.drop_index("ix_automl_studies_status_created", table_name="automl_studies")
    op.drop_index("ix_automl_studies_requester_created", table_name="automl_studies")
    op.drop_table("automl_studies")
