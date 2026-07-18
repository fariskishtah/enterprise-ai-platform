"""Add prediction events and exact-version reference profiles.

Revision ID: 0007_add_ai_prediction_monitoring
Revises: 0006_add_ai_jobs_and_promotion
Create Date: 2026-07-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_add_ai_prediction_monitoring"
down_revision: str | None = "0006_add_ai_jobs_and_promotion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prediction_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("registered_model_name", sa.String(length=128), nullable=False),
        sa.Column("requested_model_reference", sa.String(length=128), nullable=False),
        sa.Column("resolved_model_version", sa.String(length=128), nullable=True),
        sa.Column("resolved_aliases", sa.JSON(), nullable=False),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("feature_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("feature_profile", sa.JSON(), nullable=False),
        sa.Column("prediction_profile", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("safe_error_message", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_prediction_events_status_valid",
        ),
        sa.CheckConstraint(
            "duration_ms >= 0",
            name="ck_prediction_events_duration_nonnegative",
        ),
        sa.CheckConstraint(
            "row_count >= 0 AND feature_count >= 0",
            name="ck_prediction_events_dimensions_nonnegative",
        ),
        sa.CheckConstraint(
            "status != 'succeeded' OR row_count > 0",
            name="ck_prediction_events_success_rows_positive",
        ),
        sa.CheckConstraint(
            "algorithm IN ('random_forest')",
            name="ck_prediction_events_algorithm_valid",
        ),
        sa.CheckConstraint(
            "task_type IN ('regression', 'classification')",
            name="ck_prediction_events_task_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prediction_events_model_name",
        "prediction_events",
        ["registered_model_name"],
    )
    op.create_index(
        "ix_prediction_events_model_version",
        "prediction_events",
        ["registered_model_name", "resolved_model_version"],
    )
    op.create_index(
        "ix_prediction_events_task_type",
        "prediction_events",
        ["task_type"],
    )
    op.create_index(
        "ix_prediction_events_status",
        "prediction_events",
        ["status"],
    )
    op.create_index(
        "ix_prediction_events_created_at",
        "prediction_events",
        ["created_at"],
    )
    op.create_index(
        "ix_prediction_events_requested_by",
        "prediction_events",
        ["requested_by_user_id"],
    )
    op.create_index(
        "ix_prediction_events_model_window",
        "prediction_events",
        ["registered_model_name", "resolved_model_version", "created_at"],
    )

    op.create_table(
        "model_reference_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("registered_model_name", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("feature_count", sa.Integer(), nullable=False),
        sa.Column("feature_profiles", sa.JSON(), nullable=False),
        sa.Column("prediction_profile", sa.JSON(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("training_job_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source = 'evaluation'",
            name="ck_model_reference_profiles_source_valid",
        ),
        sa.CheckConstraint(
            "feature_count > 0 AND sample_count > 0",
            name="ck_model_reference_profiles_dimensions_positive",
        ),
        sa.CheckConstraint(
            "algorithm IN ('random_forest')",
            name="ck_model_reference_profiles_algorithm_valid",
        ),
        sa.CheckConstraint(
            "task_type IN ('regression', 'classification')",
            name="ck_model_reference_profiles_task_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["training_job_id"],
            ["training_jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "registered_model_name",
            "model_version",
            name="uq_model_reference_profiles_version",
        ),
    )
    op.create_index(
        "ix_model_reference_profiles_model_version",
        "model_reference_profiles",
        ["registered_model_name", "model_version"],
        unique=True,
    )
    op.create_index(
        "ix_model_reference_profiles_training_job",
        "model_reference_profiles",
        ["training_job_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_reference_profiles_training_job",
        table_name="model_reference_profiles",
    )
    op.drop_index(
        "ix_model_reference_profiles_model_version",
        table_name="model_reference_profiles",
    )
    op.drop_table("model_reference_profiles")
    op.drop_index("ix_prediction_events_model_window", table_name="prediction_events")
    op.drop_index("ix_prediction_events_requested_by", table_name="prediction_events")
    op.drop_index("ix_prediction_events_created_at", table_name="prediction_events")
    op.drop_index("ix_prediction_events_status", table_name="prediction_events")
    op.drop_index("ix_prediction_events_task_type", table_name="prediction_events")
    op.drop_index("ix_prediction_events_model_version", table_name="prediction_events")
    op.drop_index("ix_prediction_events_model_name", table_name="prediction_events")
    op.drop_table("prediction_events")
