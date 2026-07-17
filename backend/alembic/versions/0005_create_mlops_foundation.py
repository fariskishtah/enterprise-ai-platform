"""Create MLOps foundation tables.

Revision ID: 0005_create_mlops_foundation
Revises: 0004_create_sensor_data_platform
Create Date: 2026-07-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_create_mlops_foundation"
down_revision: str | None = "0004_create_sensor_data_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_experiments_name", "experiments", ["name"], unique=True)
    op.create_index("ix_experiments_created_by", "experiments", ["created_by"])
    op.create_index("ix_experiments_created_at", "experiments", ["created_at"])

    op.create_table(
        "training_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("experiment_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version", sa.String(length=128), nullable=False),
        sa.Column("algorithm", sa.String(length=128), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELED')",
            name="ck_training_runs_status_valid",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_training_runs_finished_after_started",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_training_runs_experiment_id",
        "training_runs",
        ["experiment_id"],
    )
    op.create_index(
        "ix_training_runs_dataset_version",
        "training_runs",
        ["dataset_version"],
    )
    op.create_index("ix_training_runs_algorithm", "training_runs", ["algorithm"])
    op.create_index("ix_training_runs_status", "training_runs", ["status"])
    op.create_index("ix_training_runs_started_at", "training_runs", ["started_at"])
    op.create_index(
        "ix_training_runs_experiment_status",
        "training_runs",
        ["experiment_id", "status"],
    )

    op.create_table(
        "model_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("training_run_id", sa.Uuid(), nullable=False),
        sa.Column("framework", sa.String(length=128), nullable=False),
        sa.Column("model_type", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=128), nullable=False),
        sa.Column("artifact_path", sa.String(length=1024), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "length(checksum) = 64",
            name="ck_model_artifacts_checksum_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["training_run_id"],
            ["training_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_model_artifacts_training_run_id",
        "model_artifacts",
        ["training_run_id"],
    )
    op.create_index(
        "ix_model_artifacts_framework",
        "model_artifacts",
        ["framework"],
    )
    op.create_index(
        "ix_model_artifacts_model_type",
        "model_artifacts",
        ["model_type"],
    )
    op.create_index("ix_model_artifacts_version", "model_artifacts", ["version"])
    op.create_index(
        "ix_model_artifacts_artifact_path",
        "model_artifacts",
        ["artifact_path"],
        unique=True,
    )
    op.create_index(
        "ix_model_artifacts_training_run_version",
        "model_artifacts",
        ["training_run_id", "version"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_artifacts_training_run_version",
        table_name="model_artifacts",
    )
    op.drop_index("ix_model_artifacts_artifact_path", table_name="model_artifacts")
    op.drop_index("ix_model_artifacts_version", table_name="model_artifacts")
    op.drop_index("ix_model_artifacts_model_type", table_name="model_artifacts")
    op.drop_index("ix_model_artifacts_framework", table_name="model_artifacts")
    op.drop_index("ix_model_artifacts_training_run_id", table_name="model_artifacts")
    op.drop_table("model_artifacts")
    op.drop_index("ix_training_runs_experiment_status", table_name="training_runs")
    op.drop_index("ix_training_runs_started_at", table_name="training_runs")
    op.drop_index("ix_training_runs_status", table_name="training_runs")
    op.drop_index("ix_training_runs_algorithm", table_name="training_runs")
    op.drop_index("ix_training_runs_dataset_version", table_name="training_runs")
    op.drop_index("ix_training_runs_experiment_id", table_name="training_runs")
    op.drop_table("training_runs")
    op.drop_index("ix_experiments_created_at", table_name="experiments")
    op.drop_index("ix_experiments_created_by", table_name="experiments")
    op.drop_index("ix_experiments_name", table_name="experiments")
    op.drop_table("experiments")
