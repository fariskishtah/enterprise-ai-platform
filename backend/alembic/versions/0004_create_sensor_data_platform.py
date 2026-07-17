"""Create sensor data platform.

Revision ID: 0004_create_sensor_data_platform
Revises: 0003_create_sensors
Create Date: 2026-07-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_create_sensor_data_platform"
down_revision: str | None = "0003_create_sensors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "upload_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("total_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("valid_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("invalid_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('CSV', 'API', 'SIMULATION')",
            name="ck_upload_jobs_source_valid",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="ck_upload_jobs_status_valid",
        ),
        sa.CheckConstraint(
            "total_rows >= 0 AND valid_rows >= 0 AND invalid_rows >= 0",
            name="ck_upload_jobs_row_counts_non_negative",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="ck_upload_jobs_finished_after_started",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_upload_jobs_created_by", "upload_jobs", ["created_by"])
    op.create_index("ix_upload_jobs_status", "upload_jobs", ["status"])
    op.create_index("ix_upload_jobs_source", "upload_jobs", ["source"])
    op.create_index("ix_upload_jobs_created_at", "upload_jobs", ["created_at"])
    op.create_index(
        "ix_upload_jobs_status_created",
        "upload_jobs",
        ["status", "created_at"],
    )

    op.create_table(
        "sensor_readings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sensor_id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("quality", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quality IN ('GOOD', 'BAD', 'MISSING', 'OUTLIER')",
            name="ck_sensor_readings_quality_valid",
        ),
        sa.CheckConstraint(
            "source IN ('CSV', 'API', 'SIMULATION')",
            name="ck_sensor_readings_source_valid",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["upload_jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sensor_id"], ["sensors.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sensor_readings_sensor_id", "sensor_readings", ["sensor_id"])
    op.create_index("ix_sensor_readings_timestamp", "sensor_readings", ["timestamp"])
    op.create_index("ix_sensor_readings_batch_id", "sensor_readings", ["batch_id"])
    op.create_index("ix_sensor_readings_quality", "sensor_readings", ["quality"])
    op.create_index("ix_sensor_readings_source", "sensor_readings", ["source"])
    op.create_index("ix_sensor_readings_created_at", "sensor_readings", ["created_at"])
    op.create_index(
        "ix_sensor_readings_sensor_timestamp",
        "sensor_readings",
        ["sensor_id", "timestamp"],
    )
    op.create_index(
        "ix_sensor_readings_batch_timestamp",
        "sensor_readings",
        ["batch_id", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_sensor_readings_batch_timestamp", table_name="sensor_readings")
    op.drop_index("ix_sensor_readings_sensor_timestamp", table_name="sensor_readings")
    op.drop_index("ix_sensor_readings_created_at", table_name="sensor_readings")
    op.drop_index("ix_sensor_readings_source", table_name="sensor_readings")
    op.drop_index("ix_sensor_readings_quality", table_name="sensor_readings")
    op.drop_index("ix_sensor_readings_batch_id", table_name="sensor_readings")
    op.drop_index("ix_sensor_readings_timestamp", table_name="sensor_readings")
    op.drop_index("ix_sensor_readings_sensor_id", table_name="sensor_readings")
    op.drop_table("sensor_readings")
    op.drop_index("ix_upload_jobs_status_created", table_name="upload_jobs")
    op.drop_index("ix_upload_jobs_created_at", table_name="upload_jobs")
    op.drop_index("ix_upload_jobs_source", table_name="upload_jobs")
    op.drop_index("ix_upload_jobs_status", table_name="upload_jobs")
    op.drop_index("ix_upload_jobs_created_by", table_name="upload_jobs")
    op.drop_table("upload_jobs")
