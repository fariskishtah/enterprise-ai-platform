"""Add persisted monitoring orchestration, alerts, and prediction outcomes.

Revision ID: 0009_add_monitoring_orchestration
Revises: 0008_add_controlled_retraining
Create Date: 2026-07-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_add_monitoring_orchestration"
down_revision: str | None = "0008_add_controlled_retraining"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_monitoring_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("registered_model_name", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("model_alias", sa.String(128), nullable=True),
        sa.Column("algorithm", sa.String(32), nullable=False),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_sample_count", sa.Integer(), nullable=False),
        sa.Column("successful_prediction_count", sa.Integer(), nullable=False),
        sa.Column("failed_prediction_count", sa.Integer(), nullable=False),
        sa.Column("data_quality_status", sa.String(32), nullable=False),
        sa.Column("feature_drift_status", sa.String(32), nullable=False),
        sa.Column("prediction_drift_status", sa.String(32), nullable=False),
        sa.Column("operational_health_status", sa.String(32), nullable=False),
        sa.Column("overall_status", sa.String(32), nullable=False),
        sa.Column("report_schema_version", sa.String(32), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("critical_count", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
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
            "window_start < window_end", name="ck_monitoring_evaluation_window"
        ),
        sa.CheckConstraint(
            "evaluated_sample_count >= 0 AND successful_prediction_count >= 0 "
            "AND failed_prediction_count >= 0 AND warning_count >= 0 "
            "AND critical_count >= 0",
            name="ck_monitoring_evaluation_counts",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "registered_model_name",
            "model_version",
            "window_start",
            "window_end",
            name="uq_monitoring_evaluation_model_window",
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_monitoring_evaluation_idempotency"
        ),
    )
    op.create_index(
        "ix_monitoring_evaluation_model_version_time",
        "model_monitoring_evaluations",
        ["registered_model_name", "model_version", "window_end"],
    )
    op.create_index(
        "ix_monitoring_evaluation_status_time",
        "model_monitoring_evaluations",
        ["overall_status", "created_at"],
    )

    with op.batch_alter_table("model_retraining_requests") as batch_op:
        batch_op.add_column(
            sa.Column("monitoring_evaluation_id", sa.Uuid(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_retraining_request_monitoring_evaluation",
            "model_monitoring_evaluations",
            ["monitoring_evaluation_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_unique_constraint(
            "uq_retraining_request_monitoring_evaluation",
            ["monitoring_evaluation_id"],
        )
    op.create_index(
        "ix_retraining_request_monitoring_evaluation",
        "model_retraining_requests",
        ["monitoring_evaluation_id"],
    )
    with op.batch_alter_table("model_retraining_audits") as batch_op:
        batch_op.add_column(
            sa.Column("monitoring_evaluation_id", sa.Uuid(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_retraining_audit_monitoring_evaluation",
            "model_monitoring_evaluations",
            ["monitoring_evaluation_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_retraining_audit_monitoring_evaluation",
        "model_retraining_audits",
        ["monitoring_evaluation_id"],
    )

    op.create_table(
        "monitoring_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alert_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("registered_model_name", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("monitoring_evaluation_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("safe_summary", sa.Text(), nullable=False),
        sa.Column("deduplication_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            "occurrence_count > 0", name="ck_monitoring_alert_occurrences"
        ),
        sa.ForeignKeyConstraint(
            ["monitoring_evaluation_id"],
            ["model_monitoring_evaluations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["acknowledged_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "deduplication_key", name="uq_monitoring_alert_deduplication"
        ),
    )
    op.create_index(
        "ix_monitoring_alert_model_status",
        "monitoring_alerts",
        ["registered_model_name", "model_version", "status"],
    )
    op.create_index(
        "ix_monitoring_alert_severity_time",
        "monitoring_alerts",
        ["severity", "last_detected_at"],
    )
    op.create_index(
        "ix_monitoring_alert_evaluation",
        "monitoring_alerts",
        ["monitoring_evaluation_id"],
    )

    op.create_table(
        "monitoring_job_locks",
        sa.Column("lock_key", sa.String(128), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("lock_key"),
    )

    op.create_table(
        "prediction_outcomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prediction_event_id", sa.Uuid(), nullable=False),
        sa.Column("outcome_type", sa.String(32), nullable=False),
        sa.Column("actual_value", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("label_maturity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("safe_metadata", sa.JSON(), nullable=False),
        sa.Column("external_reference_key", sa.String(128), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["prediction_event_id"], ["prediction_events.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prediction_event_id", name="uq_prediction_outcome_event"),
        sa.UniqueConstraint(
            "external_reference_key", name="uq_prediction_outcome_external_reference"
        ),
    )
    op.create_index(
        "ix_prediction_outcome_maturity",
        "prediction_outcomes",
        ["label_maturity_at"],
    )
    op.create_index(
        "ix_prediction_outcome_type", "prediction_outcomes", ["outcome_type"]
    )


def downgrade() -> None:
    op.drop_index("ix_prediction_outcome_type", table_name="prediction_outcomes")
    op.drop_index("ix_prediction_outcome_maturity", table_name="prediction_outcomes")
    op.drop_table("prediction_outcomes")
    op.drop_table("monitoring_job_locks")
    op.drop_index("ix_monitoring_alert_evaluation", table_name="monitoring_alerts")
    op.drop_index("ix_monitoring_alert_severity_time", table_name="monitoring_alerts")
    op.drop_index("ix_monitoring_alert_model_status", table_name="monitoring_alerts")
    op.drop_table("monitoring_alerts")
    op.drop_index(
        "ix_retraining_audit_monitoring_evaluation",
        table_name="model_retraining_audits",
    )
    with op.batch_alter_table("model_retraining_audits") as batch_op:
        batch_op.drop_constraint(
            "fk_retraining_audit_monitoring_evaluation", type_="foreignkey"
        )
        batch_op.drop_column("monitoring_evaluation_id")
    op.drop_index(
        "ix_retraining_request_monitoring_evaluation",
        table_name="model_retraining_requests",
    )
    with op.batch_alter_table("model_retraining_requests") as batch_op:
        batch_op.drop_constraint(
            "uq_retraining_request_monitoring_evaluation", type_="unique"
        )
        batch_op.drop_constraint(
            "fk_retraining_request_monitoring_evaluation", type_="foreignkey"
        )
        batch_op.drop_column("monitoring_evaluation_id")
    op.drop_index(
        "ix_monitoring_evaluation_status_time",
        table_name="model_monitoring_evaluations",
    )
    op.drop_index(
        "ix_monitoring_evaluation_model_version_time",
        table_name="model_monitoring_evaluations",
    )
    op.drop_table("model_monitoring_evaluations")
