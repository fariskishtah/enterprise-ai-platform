"""Add owner-isolated RAG indexing, conversations, and citations.

Revision ID: 0014_add_secure_rag_chat
Revises: 0013_integrate_dataset_training
Create Date: 2026-07-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

revision: str = "0014_add_secure_rag_chat"
down_revision: str | None = "0013_integrate_dataset_training"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # The extension is intentionally retained on downgrade because it can be
        # shared by other schemas. Production migration roles must be allowed to
        # create it once or have it pre-provisioned by the database administrator.
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    embedding_type = VECTOR(256) if bind.dialect.name == "postgresql" else sa.JSON()
    op.create_table(
        "rag_knowledge_bases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("embedding_provider", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("chunking_configuration", sa.JSON(), nullable=False),
        sa.Column("active_index_build_id", sa.Uuid(), nullable=True),
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
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("safe_error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft','indexing','ready','failed','archived')",
            name="ck_rag_knowledge_bases_status",
        ),
        sa.CheckConstraint(
            "embedding_dimension = 256",
            name="ck_rag_knowledge_bases_embedding_dimension",
        ),
        sa.CheckConstraint(
            "state_version >= 0", name="ck_rag_knowledge_bases_state_version"
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_user_id",
            "normalized_name",
            name="uq_rag_knowledge_bases_owner_name",
        ),
    )
    op.create_index(
        "ix_rag_knowledge_bases_owner_created",
        "rag_knowledge_bases",
        ["owner_user_id", "created_at"],
    )
    op.create_index(
        "ix_rag_knowledge_bases_status_created",
        "rag_knowledge_bases",
        ["status", "created_at"],
    )

    op.create_table(
        "rag_knowledge_base_dataset_versions",
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column(
            "attached_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["rag_knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("knowledge_base_id", "dataset_version_id"),
    )
    op.create_index(
        "ix_rag_kb_dataset_versions_version",
        "rag_knowledge_base_dataset_versions",
        ["dataset_version_id"],
    )

    op.create_table(
        "rag_index_builds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), server_default="queued", nullable=False),
        sa.Column(
            "indexed_document_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "indexed_chunk_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("embedding_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "enqueue_attempt_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("safe_error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_rag_index_builds_status",
        ),
        sa.CheckConstraint(
            "indexed_document_count >= 0 AND indexed_chunk_count >= 0 "
            "AND embedding_count >= 0",
            name="ck_rag_index_builds_counts",
        ),
        sa.CheckConstraint(
            "state_version >= 0", name="ck_rag_index_builds_state_version"
        ),
        sa.CheckConstraint(
            "enqueue_attempt_count BETWEEN 0 AND 100",
            name="ck_rag_index_builds_enqueue_attempts",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["rag_knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rag_index_builds_kb_created",
        "rag_index_builds",
        ["knowledge_base_id", "created_at"],
    )
    op.create_index(
        "ix_rag_index_builds_status_created",
        "rag_index_builds",
        ["status", "created_at"],
    )
    with op.batch_alter_table("rag_knowledge_bases") as batch:
        batch.create_foreign_key(
            "fk_rag_knowledge_bases_active_build",
            "rag_index_builds",
            ["active_index_build_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "rag_indexed_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("index_build_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("chunk_number >= 0", name="ck_rag_indexed_chunks_number"),
        sa.CheckConstraint(
            "character_count BETWEEN 1 AND 4000",
            name="ck_rag_indexed_chunks_character_count",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["rag_knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["index_build_id"], ["rag_index_builds.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["document_records.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "index_build_id",
            "document_id",
            "chunk_number",
            name="uq_rag_indexed_chunks_build_document_number",
        ),
    )
    op.create_index(
        "ix_rag_indexed_chunks_scope",
        "rag_indexed_chunks",
        ["knowledge_base_id", "index_build_id"],
    )
    op.create_index(
        "ix_rag_indexed_chunks_document", "rag_indexed_chunks", ["document_id"]
    )

    op.create_table(
        "rag_chunk_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("index_build_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", embedding_type, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "embedding_dimension = 256", name="ck_rag_chunk_embeddings_dimension"
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["rag_knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["index_build_id"], ["rag_index_builds.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["rag_indexed_chunks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["document_records.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "index_build_id", "chunk_id", name="uq_rag_chunk_embeddings_build_chunk"
        ),
    )
    op.create_index(
        "ix_rag_chunk_embeddings_scope",
        "rag_chunk_embeddings",
        ["knowledge_base_id", "index_build_id"],
    )
    op.create_index(
        "ix_rag_chunk_embeddings_chunk", "rag_chunk_embeddings", ["chunk_id"]
    )

    op.create_table(
        "rag_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
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
        sa.CheckConstraint(
            "status IN ('active','archived')", name="ck_rag_conversations_status"
        ),
        sa.CheckConstraint(
            "state_version >= 0", name="ck_rag_conversations_state_version"
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["rag_knowledge_bases.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rag_conversations_owner_updated",
        "rag_conversations",
        ["owner_user_id", "updated_at"],
    )
    op.create_index(
        "ix_rag_conversations_kb", "rag_conversations", ["knowledge_base_id"]
    )

    op.create_table(
        "rag_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("reply_to_message_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("grounded_outcome", sa.String(32), nullable=True),
        sa.Column("generation_provider", sa.String(64), nullable=True),
        sa.Column("generation_model", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("safe_error_message", sa.Text(), nullable=True),
        sa.CheckConstraint("role IN ('user','assistant')", name="ck_rag_messages_role"),
        sa.CheckConstraint(
            "status IN ('queued','retrieving','generating','succeeded',"
            "'failed','cancelled')",
            name="ck_rag_messages_status",
        ),
        sa.CheckConstraint(
            "grounded_outcome IS NULL OR grounded_outcome IN "
            "('grounded','insufficient_evidence')",
            name="ck_rag_messages_grounded_outcome",
        ),
        sa.CheckConstraint(
            "character_count >= 0 AND character_count <= 16000",
            name="ck_rag_messages_character_count",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["rag_conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reply_to_message_id"], ["rag_messages.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id", "idempotency_key", name="uq_rag_messages_idempotency"
        ),
    )
    op.create_index(
        "ix_rag_messages_conversation_created",
        "rag_messages",
        ["conversation_id", "created_at"],
    )
    op.create_index("ix_rag_messages_reply", "rag_messages", ["reply_to_message_id"])

    op.create_table(
        "rag_message_citations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("excerpt", sa.String(600), nullable=False),
        sa.Column("document_title", sa.String(255), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("rank BETWEEN 1 AND 20", name="ck_rag_citations_rank"),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="ck_rag_citations_score"),
        sa.ForeignKeyConstraint(
            ["message_id"], ["rag_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["rag_indexed_chunks.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["document_records.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "rank", name="uq_rag_citations_message_rank"),
        sa.UniqueConstraint(
            "message_id", "chunk_id", name="uq_rag_citations_message_chunk"
        ),
    )
    op.create_index(
        "ix_rag_citations_dataset_version",
        "rag_message_citations",
        ["dataset_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_rag_citations_dataset_version", table_name="rag_message_citations"
    )
    op.drop_table("rag_message_citations")
    op.drop_index("ix_rag_messages_reply", table_name="rag_messages")
    op.drop_index("ix_rag_messages_conversation_created", table_name="rag_messages")
    op.drop_table("rag_messages")
    op.drop_index("ix_rag_conversations_kb", table_name="rag_conversations")
    op.drop_index("ix_rag_conversations_owner_updated", table_name="rag_conversations")
    op.drop_table("rag_conversations")
    op.drop_index("ix_rag_chunk_embeddings_chunk", table_name="rag_chunk_embeddings")
    op.drop_index("ix_rag_chunk_embeddings_scope", table_name="rag_chunk_embeddings")
    op.drop_table("rag_chunk_embeddings")
    op.drop_index("ix_rag_indexed_chunks_document", table_name="rag_indexed_chunks")
    op.drop_index("ix_rag_indexed_chunks_scope", table_name="rag_indexed_chunks")
    op.drop_table("rag_indexed_chunks")
    with op.batch_alter_table("rag_knowledge_bases") as batch:
        batch.drop_constraint("fk_rag_knowledge_bases_active_build", type_="foreignkey")
    op.drop_index("ix_rag_index_builds_status_created", table_name="rag_index_builds")
    op.drop_index("ix_rag_index_builds_kb_created", table_name="rag_index_builds")
    op.drop_table("rag_index_builds")
    op.drop_index(
        "ix_rag_kb_dataset_versions_version",
        table_name="rag_knowledge_base_dataset_versions",
    )
    op.drop_table("rag_knowledge_base_dataset_versions")
    op.drop_index(
        "ix_rag_knowledge_bases_status_created", table_name="rag_knowledge_bases"
    )
    op.drop_index(
        "ix_rag_knowledge_bases_owner_created", table_name="rag_knowledge_bases"
    )
    op.drop_table("rag_knowledge_bases")
