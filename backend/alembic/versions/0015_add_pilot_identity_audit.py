"""Add pilot tenant identity, audit, governed inputs, and machine risk.

Revision ID: 0015_add_pilot_identity_audit
Revises: 0014_add_secure_rag_chat
Create Date: 2026-07-23 00:00:00.000000
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0015_add_pilot_identity_audit"
down_revision: str | None = "0014_add_secure_rag_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_COMPANY_ID = UUID("00000000-0000-4000-8000-000000000001")
_CANONICAL_COMPANY_SQL = (
    "(SELECT id FROM companies ORDER BY created_at ASC, id ASC LIMIT 1)"
)
_SUPPORTED_ALGORITHMS = (
    "'random_forest','logistic_regression','decision_tree','extra_trees',"
    "'knn','svm','gradient_boosting','linear_regression','ridge','lasso',"
    "'elastic_net','xgboost','lightgbm','catboost'"
)


def _company_column() -> sa.Column[object]:
    return sa.Column("company_id", sa.Uuid(), nullable=True)


def _add_company_scope(table_name: str) -> None:
    with op.batch_alter_table(table_name) as batch:
        batch.add_column(_company_column())
        batch.create_foreign_key(
            f"fk_{table_name}_company_id",
            "companies",
            ["company_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def _backfill_from_user(table_name: str, user_column: str) -> None:
    op.execute(
        sa.text(
            f"UPDATE {table_name} SET company_id = "
            f"(SELECT users.company_id FROM users "
            f"WHERE users.id = {table_name}.{user_column}) "
            "WHERE company_id IS NULL"
        )
    )


def _finish_company_scope(
    table_name: str,
    index_name: str,
    index_columns: list[str],
) -> None:
    op.execute(
        sa.text(
            f"UPDATE {table_name} SET company_id = {_CANONICAL_COMPANY_SQL} "
            "WHERE company_id IS NULL"
        )
    )
    with op.batch_alter_table(table_name) as batch:
        batch.alter_column("company_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_index(
            index_name,
            ["company_id", *index_columns],
            unique=False,
        )


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO companies "
            "(id, name, normalized_name, description) "
            "SELECT :id, :name, :normalized, :description "
            "WHERE EXISTS (SELECT 1 FROM users) "
            "AND NOT EXISTS (SELECT 1 FROM companies) "
            "AND NOT EXISTS (SELECT 1 FROM companies WHERE id = :id)"
        ).bindparams(
            id=_LEGACY_COMPANY_ID,
            name="Legacy Pilot Tenant",
            normalized="legacy pilot tenant",
            description="Migration boundary for pre-tenant 0.9 data.",
        )
    )

    with op.batch_alter_table("users") as batch:
        batch.add_column(_company_column())
        batch.create_foreign_key(
            "fk_users_company_id",
            "companies",
            ["company_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.execute(
        sa.text(
            f"UPDATE users SET company_id = {_CANONICAL_COMPANY_SQL} "
            "WHERE company_id IS NULL"
        )
    )
    with op.batch_alter_table("users") as batch:
        batch.alter_column("company_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_index("ix_users_company_role", ["company_id", "role"])

    scoped_from_user = {
        "datasets": "owner_user_id",
        "training_jobs": "requested_by_user_id",
        "model_promotion_audits": "requested_by_user_id",
        "prediction_events": "requested_by_user_id",
        "automl_studies": "requested_by_user_id",
        "model_retraining_policies": "created_by_user_id",
        "model_retraining_requests": "requested_by_user_id",
        "model_retraining_audits": "evaluated_by_user_id",
        "rag_knowledge_bases": "owner_user_id",
        "rag_conversations": "owner_user_id",
        "upload_jobs": "created_by",
        "experiments": "created_by",
    }
    inherited_or_legacy = (
        "model_reference_profiles",
        "model_monitoring_evaluations",
        "monitoring_alerts",
        "prediction_outcomes",
    )
    for table_name in (*scoped_from_user, *inherited_or_legacy):
        _add_company_scope(table_name)
    for table_name, user_column in scoped_from_user.items():
        _backfill_from_user(table_name, user_column)
    company_indexes = {
        "datasets": ("ix_datasets_company_created", ["created_at"]),
        "training_jobs": ("ix_training_jobs_company_created", ["created_at"]),
        "model_promotion_audits": (
            "ix_model_promotion_audits_company",
            ["created_at"],
        ),
        "prediction_events": ("ix_prediction_events_company_time", ["created_at"]),
        "automl_studies": ("ix_automl_studies_company_created", ["created_at"]),
        "model_retraining_policies": ("ix_retraining_policy_company", []),
        "model_retraining_requests": (
            "ix_retraining_request_company",
            ["requested_at"],
        ),
        "model_retraining_audits": (
            "ix_retraining_audit_company",
            ["evaluated_at"],
        ),
        "rag_knowledge_bases": (
            "ix_rag_knowledge_bases_company_created",
            ["created_at"],
        ),
        "rag_conversations": (
            "ix_rag_conversations_company_updated",
            ["updated_at"],
        ),
        "upload_jobs": ("ix_upload_jobs_company_created", ["created_at"]),
        "experiments": ("ix_experiments_company_created", ["created_at"]),
        "model_reference_profiles": (
            "ix_model_reference_profiles_company_model",
            ["registered_model_name", "model_version"],
        ),
        "model_monitoring_evaluations": (
            "ix_monitoring_evaluation_company_time",
            ["created_at"],
        ),
        "monitoring_alerts": (
            "ix_monitoring_alert_company_status",
            ["status"],
        ),
        "prediction_outcomes": (
            "ix_prediction_outcome_company",
            ["created_at"],
        ),
    }
    for table_name, (index_name, index_columns) in company_indexes.items():
        _finish_company_scope(table_name, index_name, index_columns)

    with op.batch_alter_table("prediction_events") as batch:
        batch.drop_constraint("ck_prediction_events_algorithm_valid", type_="check")
        batch.create_check_constraint(
            "ck_prediction_events_algorithm_valid",
            f"algorithm IN ({_SUPPORTED_ALGORITHMS})",
        )
    with op.batch_alter_table("model_reference_profiles") as batch:
        batch.drop_constraint(
            "ck_model_reference_profiles_algorithm_valid", type_="check"
        )
        batch.create_check_constraint(
            "ck_model_reference_profiles_algorithm_valid",
            f"algorithm IN ({_SUPPORTED_ALGORITHMS})",
        )
        batch.drop_constraint("uq_model_reference_profiles_version", type_="unique")
        batch.drop_index("ix_model_reference_profiles_model_version")
        batch.create_unique_constraint(
            "uq_model_reference_profiles_version",
            ["company_id", "registered_model_name", "model_version"],
        )
        batch.create_index(
            "ix_model_reference_profiles_model_version",
            ["company_id", "registered_model_name", "model_version"],
            unique=True,
        )

    with op.batch_alter_table("datasets") as batch:
        batch.drop_constraint("uq_datasets_owner_name", type_="unique")
        batch.create_unique_constraint(
            "uq_datasets_company_name", ["company_id", "normalized_name"]
        )
    with op.batch_alter_table("rag_knowledge_bases") as batch:
        batch.drop_constraint(
            "uq_rag_knowledge_bases_owner_name",
            type_="unique",
        )
        batch.create_unique_constraint(
            "uq_rag_knowledge_bases_company_name",
            ["company_id", "normalized_name"],
        )
    with op.batch_alter_table("model_retraining_policies") as batch:
        batch.drop_constraint(
            "uq_retraining_policy_model_name",
            type_="unique",
        )
        batch.create_unique_constraint(
            "uq_retraining_policy_model_name",
            ["company_id", "registered_model_name"],
        )

    with op.batch_alter_table("refresh_tokens") as batch:
        batch.add_column(sa.Column("last_seen_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("user_agent_summary", sa.String(255)))
        batch.add_column(sa.Column("source_ip", sa.String(64)))

    with op.batch_alter_table("monitoring_alerts") as batch:
        batch.add_column(sa.Column("factory_id", sa.Uuid()))
        batch.add_column(sa.Column("machine_id", sa.Uuid()))
        batch.add_column(sa.Column("operator_note", sa.Text()))
        batch.add_column(sa.Column("engineer_note", sa.Text()))
        batch.add_column(sa.Column("cooldown_until", sa.DateTime(timezone=True)))
        batch.create_foreign_key(
            "fk_monitoring_alerts_factory_id",
            "factories",
            ["factory_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_monitoring_alerts_machine_id",
            "machines",
            ["machine_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_password_reset_tokens_hash",
        "password_reset_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_password_reset_tokens_user_expiry",
        "password_reset_tokens",
        ["user_id", "expires_at"],
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("actor_role", sa.String(32)),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128)),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(128)),
        sa.Column("correlation_id", sa.String(128)),
        sa.Column("source_ip", sa.String(64)),
        sa.Column("user_agent", sa.String(255)),
        sa.Column("safe_metadata", sa.JSON(), nullable=False),
        sa.Column("before_summary", sa.Text()),
        sa.Column("after_summary", sa.Text()),
        sa.Column(
            "retention_class",
            sa.String(32),
            server_default="security",
            nullable=False,
        ),
        sa.CheckConstraint(
            "result IN ('success', 'failure')", name="ck_audit_events_result"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_events_company_time",
        "audit_events",
        ["company_id", "occurred_at"],
    )
    op.create_index(
        "ix_audit_events_company_action",
        "audit_events",
        ["company_id", "action"],
    )
    op.create_index(
        "ix_audit_events_resource",
        "audit_events",
        ["resource_type", "resource_id"],
    )
    op.create_index(
        "ix_audit_events_actor",
        "audit_events",
        ["actor_user_id", "occurred_at"],
    )

    op.create_table(
        "model_feature_schemas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("registered_model_name", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("target_metadata", sa.JSON(), nullable=False),
        sa.Column("training_dataset_version_id", sa.Uuid()),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["training_dataset_version_id"],
            ["dataset_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "registered_model_name",
            "model_version",
            name="uq_model_feature_schema_company_version",
        ),
    )
    op.create_index(
        "ix_model_feature_schema_lookup",
        "model_feature_schemas",
        ["company_id", "registered_model_name", "model_version"],
    )

    op.create_table(
        "machine_risk_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("factory_id", sa.Uuid(), nullable=False),
        sa.Column("machine_id", sa.Uuid(), nullable=False),
        sa.Column("prediction_event_id", sa.Uuid()),
        sa.Column("alert_id", sa.Uuid()),
        sa.Column("registered_model_name", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("risk_state", sa.String(32), nullable=False),
        sa.Column("risk_score", sa.Float()),
        sa.Column("sensor_values", sa.JSON(), nullable=False),
        sa.Column("data_freshness_seconds", sa.Float()),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("monitoring_status", sa.String(32), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_by_user_id", sa.Uuid()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "risk_state IN ('normal','observe','warning','critical',"
            "'insufficient_data','model_unavailable')",
            name="ck_machine_risk_state",
        ),
        sa.CheckConstraint(
            "risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 1)",
            name="ck_machine_risk_score",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["prediction_event_id"], ["prediction_events.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"], ["monitoring_alerts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["acknowledged_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_machine_risk_company_time",
        "machine_risk_assessments",
        ["company_id", "assessed_at"],
    )
    op.create_index(
        "ix_machine_risk_machine_time",
        "machine_risk_assessments",
        ["machine_id", "assessed_at"],
    )


def downgrade() -> None:
    op.drop_table("machine_risk_assessments")
    op.drop_table("model_feature_schemas")
    op.drop_table("audit_events")
    op.drop_table("password_reset_tokens")

    with op.batch_alter_table("monitoring_alerts") as batch:
        batch.drop_constraint("fk_monitoring_alerts_machine_id", type_="foreignkey")
        batch.drop_constraint("fk_monitoring_alerts_factory_id", type_="foreignkey")
        batch.drop_column("cooldown_until")
        batch.drop_column("engineer_note")
        batch.drop_column("operator_note")
        batch.drop_column("machine_id")
        batch.drop_column("factory_id")
    with op.batch_alter_table("refresh_tokens") as batch:
        batch.drop_column("source_ip")
        batch.drop_column("user_agent_summary")
        batch.drop_column("last_seen_at")
    with op.batch_alter_table("model_reference_profiles") as batch:
        batch.drop_constraint("uq_model_reference_profiles_version", type_="unique")
        batch.drop_index("ix_model_reference_profiles_model_version")
        batch.create_unique_constraint(
            "uq_model_reference_profiles_version",
            ["registered_model_name", "model_version"],
        )
        batch.create_index(
            "ix_model_reference_profiles_model_version",
            ["registered_model_name", "model_version"],
            unique=True,
        )
        batch.drop_constraint(
            "ck_model_reference_profiles_algorithm_valid", type_="check"
        )
        batch.create_check_constraint(
            "ck_model_reference_profiles_algorithm_valid",
            "algorithm IN ('random_forest')",
        )
    with op.batch_alter_table("prediction_events") as batch:
        batch.drop_constraint("ck_prediction_events_algorithm_valid", type_="check")
        batch.create_check_constraint(
            "ck_prediction_events_algorithm_valid",
            "algorithm IN ('random_forest')",
        )
    with op.batch_alter_table("rag_knowledge_bases") as batch:
        batch.drop_constraint("uq_rag_knowledge_bases_company_name", type_="unique")
        batch.create_unique_constraint(
            "uq_rag_knowledge_bases_owner_name",
            ["owner_user_id", "normalized_name"],
        )
    with op.batch_alter_table("datasets") as batch:
        batch.drop_constraint("uq_datasets_company_name", type_="unique")
        batch.create_unique_constraint(
            "uq_datasets_owner_name",
            ["owner_user_id", "normalized_name"],
        )
    with op.batch_alter_table("model_retraining_policies") as batch:
        batch.drop_constraint(
            "uq_retraining_policy_model_name",
            type_="unique",
        )
        batch.create_unique_constraint(
            "uq_retraining_policy_model_name",
            ["registered_model_name"],
        )

    tables = (
        "prediction_outcomes",
        "monitoring_alerts",
        "model_monitoring_evaluations",
        "model_reference_profiles",
        "experiments",
        "upload_jobs",
        "rag_conversations",
        "rag_knowledge_bases",
        "model_retraining_audits",
        "model_retraining_requests",
        "model_retraining_policies",
        "automl_studies",
        "prediction_events",
        "model_promotion_audits",
        "training_jobs",
        "datasets",
    )
    company_index_names = {
        "datasets": "ix_datasets_company_created",
        "training_jobs": "ix_training_jobs_company_created",
        "model_promotion_audits": "ix_model_promotion_audits_company",
        "prediction_events": "ix_prediction_events_company_time",
        "automl_studies": "ix_automl_studies_company_created",
        "model_retraining_policies": "ix_retraining_policy_company",
        "model_retraining_requests": "ix_retraining_request_company",
        "model_retraining_audits": "ix_retraining_audit_company",
        "rag_knowledge_bases": "ix_rag_knowledge_bases_company_created",
        "rag_conversations": "ix_rag_conversations_company_updated",
        "upload_jobs": "ix_upload_jobs_company_created",
        "experiments": "ix_experiments_company_created",
        "model_reference_profiles": "ix_model_reference_profiles_company_model",
        "model_monitoring_evaluations": "ix_monitoring_evaluation_company_time",
        "monitoring_alerts": "ix_monitoring_alert_company_status",
        "prediction_outcomes": "ix_prediction_outcome_company",
    }
    for table_name in tables:
        with op.batch_alter_table(table_name) as batch:
            batch.drop_index(company_index_names[table_name])
            batch.drop_constraint(f"fk_{table_name}_company_id", type_="foreignkey")
            batch.drop_column("company_id")
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_company_role")
        batch.drop_constraint("fk_users_company_id", type_="foreignkey")
        batch.drop_column("company_id")
