"""Add the authoritative versioned Dataset Registry.

Revision ID: 0012_add_dataset_registry
Revises: 0011_adjust_automl_trial_uniqueness
Create Date: 2026-07-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_add_dataset_registry"
down_revision: str | None = "0011_adjust_automl_trial_uniqueness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("normalized_name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("state_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("state_version >= 0", name="ck_datasets_state_version"),
        sa.CheckConstraint(
            "kind IN ('tabular','document_collection')", name="ck_datasets_kind"
        ),
        sa.CheckConstraint(
            "status IN ('active','archived','failed')", name="ck_datasets_status"
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_user_id", "normalized_name", name="uq_datasets_owner_name"
        ),
    )
    op.create_index(
        "ix_datasets_owner_created", "datasets", ["owner_user_id", "created_at"]
    )
    op.create_index("ix_datasets_kind_status", "datasets", ["kind", "status"])

    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(128), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256_digest", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("column_count", sa.Integer(), nullable=True),
        sa.Column("document_count", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("schema_snapshot", sa.JSON(), nullable=False),
        sa.Column("lineage_snapshot", sa.JSON(), nullable=False),
        sa.Column("ingestion_options", sa.JSON(), nullable=False),
        sa.Column("processing_summary", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "enqueue_attempt_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("safe_error_message", sa.Text(), nullable=True),
        sa.Column("state_version", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("version_number > 0", name="ck_dataset_versions_number"),
        sa.CheckConstraint("size_bytes > 0", name="ck_dataset_versions_size"),
        sa.CheckConstraint(
            "row_count IS NULL OR row_count >= 0", name="ck_dataset_versions_rows"
        ),
        sa.CheckConstraint(
            "column_count IS NULL OR column_count >= 0",
            name="ck_dataset_versions_columns",
        ),
        sa.CheckConstraint(
            "document_count IS NULL OR document_count >= 0",
            name="ck_dataset_versions_documents",
        ),
        sa.CheckConstraint(
            "chunk_count IS NULL OR chunk_count >= 0",
            name="ck_dataset_versions_chunks",
        ),
        sa.CheckConstraint(
            "state_version >= 0", name="ck_dataset_versions_state_version"
        ),
        sa.CheckConstraint(
            "enqueue_attempt_count BETWEEN 0 AND 100",
            name="ck_dataset_versions_enqueue_attempts",
        ),
        sa.CheckConstraint(
            "status IN ('pending','processing','ready','failed','archived')",
            name="ck_dataset_versions_status",
        ),
        sa.CheckConstraint(
            "source_type IN ('upload','generated',"
            "'imported_from_existing_training_job')",
            name="ck_dataset_versions_source_type",
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset_id", "version_number", name="uq_dataset_versions_number"
        ),
        sa.UniqueConstraint(
            "dataset_id", "sha256_digest", name="uq_dataset_versions_digest"
        ),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        "ix_dataset_versions_dataset_created",
        "dataset_versions",
        ["dataset_id", "created_at"],
    )
    op.create_index(
        "ix_dataset_versions_status_created",
        "dataset_versions",
        ["status", "created_at"],
    )
    with op.batch_alter_table("datasets") as batch:
        batch.create_foreign_key(
            "fk_datasets_current_version",
            "dataset_versions",
            ["current_version_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "document_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("document_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256_digest", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "extracted_character_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("safe_error_message", sa.Text(), nullable=True),
        sa.CheckConstraint("document_number > 0", name="ck_documents_number"),
        sa.CheckConstraint(
            "status IN ('pending','extracting','chunking','embedding','ready',"
            "'failed','cancelled')",
            name="ck_documents_status",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset_version_id",
            "document_number",
            name="uq_documents_version_number",
        ),
    )
    op.create_index(
        "ix_documents_version_status",
        "document_records",
        ["dataset_version_id", "status"],
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(255), nullable=True),
        sa.Column(
            "embedding_status",
            sa.String(32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("metadata_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("chunk_number >= 0", name="ck_document_chunks_number"),
        sa.CheckConstraint(
            "character_count > 0", name="ck_document_chunks_character_count"
        ),
        sa.CheckConstraint(
            "embedding_status IN ('pending','extracting','chunking','embedding',"
            "'ready','failed','cancelled')",
            name="ck_document_chunks_embedding_status",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["document_records.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id", "chunk_number", name="uq_document_chunks_number"
        ),
        sa.UniqueConstraint(
            "dataset_version_id", "content_hash", name="uq_document_chunks_hash"
        ),
    )
    op.create_index(
        "ix_document_chunks_version",
        "document_chunks",
        ["dataset_version_id", "chunk_number"],
    )
    op.create_index(
        "ix_document_chunks_embedding", "document_chunks", ["embedding_status"]
    )

    op.create_table(
        "dataset_usage_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("usage_type", sa.String(64), nullable=False),
        sa.Column("reference_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset_version_id",
            "usage_type",
            "reference_id",
            name="uq_dataset_usage_reference",
        ),
    )
    op.create_index(
        "ix_dataset_usage_version",
        "dataset_usage_references",
        ["dataset_version_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_dataset_usage_version", table_name="dataset_usage_references")
    op.drop_table("dataset_usage_references")
    op.drop_index("ix_document_chunks_embedding", table_name="document_chunks")
    op.drop_index("ix_document_chunks_version", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_documents_version_status", table_name="document_records")
    op.drop_table("document_records")
    with op.batch_alter_table("datasets") as batch:
        batch.drop_constraint("fk_datasets_current_version", type_="foreignkey")
    op.drop_index("ix_dataset_versions_status_created", table_name="dataset_versions")
    op.drop_index("ix_dataset_versions_dataset_created", table_name="dataset_versions")
    op.drop_table("dataset_versions")
    op.drop_index("ix_datasets_kind_status", table_name="datasets")
    op.drop_index("ix_datasets_owner_created", table_name="datasets")
    op.drop_table("datasets")
