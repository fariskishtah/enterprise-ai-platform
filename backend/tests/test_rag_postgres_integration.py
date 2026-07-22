"""Opt-in PostgreSQL pgvector retrieval and ownership integration."""

from __future__ import annotations

import os
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from app import models as app_models
from app.config.settings import get_settings
from app.datasets.domain import (
    DatasetKind,
    DatasetSourceType,
    DatasetStatus,
    DatasetVersionStatus,
    DocumentProcessingStatus,
)
from app.db.base import Base
from app.models.datasets import Dataset, DatasetVersion, DocumentRecord
from app.models.rag import (
    RAGChunkEmbedding,
    RAGIndexBuild,
    RAGIndexedChunk,
    RAGKnowledgeBase,
    RAGKnowledgeBaseDatasetVersion,
)
from app.models.user import User, UserRole
from app.rag.domain import RAGIndexBuildStatus, RAGKnowledgeBaseStatus
from app.repositories.rag import RAGRepository
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

_ = app_models
RUN_POSTGRES_INTEGRATION = os.getenv("RUN_RAG_POSTGRES_INTEGRATION") == "1"


@pytest.mark.integration
@pytest.mark.skipif(
    not RUN_POSTGRES_INTEGRATION,
    reason="Set RUN_RAG_POSTGRES_INTEGRATION=1 for disposable local PostgreSQL.",
)
def test_postgres_alembic_data_rag_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the real PostgreSQL migration path in an isolated schema."""
    database_url = os.getenv(
        "RAG_TEST_POSTGRES_URL",
        "postgresql+psycopg://ai_manufacturing:ai_manufacturing_password@"
        "127.0.0.1:5432/ai_manufacturing",
    )
    parsed = urlparse(database_url.replace("postgresql+psycopg", "postgresql", 1))
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("The migration integration test requires loopback PostgreSQL.")
    if make_url(database_url).drivername != "postgresql+psycopg":
        pytest.fail("RAG_TEST_POSTGRES_URL must use the postgresql+psycopg driver.")

    schema = f"rag_migration_test_{uuid4().hex}"
    admin_engine = create_engine(database_url, pool_pre_ping=True)
    scoped_url = make_url(database_url).update_query_dict(
        {"options": f"-csearch_path={schema},public"}
    )
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))

        monkeypatch.setenv("DATABASE_URL", scoped_url.render_as_string(False))
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/15")
        monkeypatch.setenv("SECRET_KEY", "test-secret-key-with-sufficient-entropy")
        monkeypatch.setenv("ENVIRONMENT", "test")
        get_settings.cache_clear()
        config = Config("alembic.ini")

        command.upgrade(config, "head")
        with admin_engine.connect() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :schema"
                    ),
                    {"schema": schema},
                )
            }
            embedding_type = connection.scalar(
                text(
                    "SELECT format_type(attribute.atttypid, attribute.atttypmod) "
                    "FROM pg_attribute AS attribute "
                    "JOIN pg_class AS relation ON relation.oid = attribute.attrelid "
                    "JOIN pg_namespace AS namespace "
                    "ON namespace.oid = relation.relnamespace "
                    "WHERE namespace.nspname = :schema "
                    "AND relation.relname = 'rag_chunk_embeddings' "
                    "AND attribute.attname = 'embedding'"
                ),
                {"schema": schema},
            )
            vector_extension_count = connection.scalar(
                text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
            )

        assert {"datasets", "rag_knowledge_bases", "rag_chunk_embeddings"} <= tables
        assert embedding_type == "vector(256)"
        assert vector_extension_count == 1

        command.downgrade(config, "0011_adjust_automl_trial_uniqueness")
        with admin_engine.connect() as connection:
            remaining = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :schema"
                    ),
                    {"schema": schema},
                )
            }
        assert "datasets" not in remaining
        assert "rag_knowledge_bases" not in remaining

        command.upgrade(config, "head")
        with admin_engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = :schema "
                        "AND table_name IN ('datasets', 'rag_knowledge_bases')"
                    ),
                    {"schema": schema},
                )
                == 2
            )
    finally:
        get_settings.cache_clear()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(
    not RUN_POSTGRES_INTEGRATION,
    reason="Set RUN_RAG_POSTGRES_INTEGRATION=1 for disposable local PostgreSQL.",
)
@pytest.mark.anyio
async def test_pgvector_ranking_is_filtered_by_owner_and_knowledge_base() -> None:
    """Rank in PostgreSQL only after the full authorized SQL scope is applied."""
    database_url = os.getenv(
        "RAG_TEST_POSTGRES_URL",
        "postgresql+psycopg://ai_manufacturing:ai_manufacturing_password@"
        "127.0.0.1:5432/ai_manufacturing",
    )
    parsed = urlparse(database_url.replace("postgresql+psycopg", "postgresql", 1))
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("The pgvector integration test requires loopback PostgreSQL.")

    schema = f"rag_vector_test_{uuid4().hex}"
    engine = create_async_engine(database_url, pool_pre_ping=True)
    connection = await engine.connect()
    try:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'SET search_path TO "{schema}", public'))
        await connection.run_sync(Base.metadata.create_all)
        await connection.commit()

        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            owner_id, knowledge_base_id, build_id = await _seed_scoped_vectors(session)
            candidates = await RAGRepository(session).list_retrieval_candidates(
                knowledge_base_id=knowledge_base_id,
                active_build_id=build_id,
                user_id=owner_id,
                is_admin=False,
                query_embedding=_unit_vector(0),
                top_k=5,
                min_score=0.0,
                maximum_candidates=2000,
            )

        assert len(candidates) == 1
        assert candidates[0].document.title == "Authorized handbook"
        assert candidates[0].score == pytest.approx(0.8, abs=1e-5)
    finally:
        try:
            await connection.rollback()
            await connection.execute(text("SET search_path TO public"))
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await connection.commit()
        finally:
            await connection.close()
            await engine.dispose()


async def _seed_scoped_vectors(session: AsyncSession) -> tuple[UUID, UUID, UUID]:
    owner = User(
        email=f"pgvector-owner-{uuid4().hex}@example.test",
        hashed_password="not-used",
        role=UserRole.ENGINEER,
        is_active=True,
    )
    other = User(
        email=f"pgvector-other-{uuid4().hex}@example.test",
        hashed_password="not-used",
        role=UserRole.ENGINEER,
        is_active=True,
    )
    session.add_all((owner, other))
    await session.flush()

    authorized_version, authorized_document = await _document_version(
        session,
        owner_id=owner.id,
        name="Authorized vector data",
        title="Authorized handbook",
    )
    unauthorized_version, unauthorized_document = await _document_version(
        session,
        owner_id=other.id,
        name="Other owner vector data",
        title="Other owner's handbook",
    )
    knowledge_base = RAGKnowledgeBase(
        owner_user_id=owner.id,
        name="PostgreSQL vector scope",
        normalized_name=f"postgresql-vector-scope-{uuid4().hex}",
        description=None,
        status=RAGKnowledgeBaseStatus.DRAFT,
        embedding_provider="local_hashing",
        embedding_model="hashing-v1",
        embedding_dimension=256,
        chunking_configuration={
            "chunk_size": 1000,
            "chunk_overlap": 100,
            "maximum_chunks": 2000,
        },
        state_version=0,
    )
    session.add(knowledge_base)
    await session.flush()
    build = RAGIndexBuild(
        knowledge_base_id=knowledge_base.id,
        requested_by_user_id=owner.id,
        status=RAGIndexBuildStatus.SUCCEEDED,
        indexed_document_count=1,
        indexed_chunk_count=1,
        embedding_count=1,
        state_version=1,
    )
    session.add(build)
    await session.flush()
    knowledge_base.status = RAGKnowledgeBaseStatus.READY
    knowledge_base.active_index_build_id = build.id
    session.add_all(
        (
            RAGKnowledgeBaseDatasetVersion(
                knowledge_base_id=knowledge_base.id,
                dataset_version_id=authorized_version.id,
            ),
            # Simulate a corrupt lower-level association. The repository's owner
            # predicate must still exclude this closer vector before ranking.
            RAGKnowledgeBaseDatasetVersion(
                knowledge_base_id=knowledge_base.id,
                dataset_version_id=unauthorized_version.id,
            ),
        )
    )
    await session.flush()
    await _indexed_vector(
        session,
        knowledge_base_id=knowledge_base.id,
        build_id=build.id,
        version_id=authorized_version.id,
        document=authorized_document,
        embedding=_normalized_vector(0.8, 0.6),
        content="Authorized maintenance evidence.",
    )
    await _indexed_vector(
        session,
        knowledge_base_id=knowledge_base.id,
        build_id=build.id,
        version_id=unauthorized_version.id,
        document=unauthorized_document,
        embedding=_unit_vector(0),
        content="Closer but unauthorized evidence.",
    )
    await session.commit()
    return owner.id, knowledge_base.id, build.id


async def _document_version(
    session: AsyncSession, *, owner_id: UUID, name: str, title: str
) -> tuple[DatasetVersion, DocumentRecord]:
    dataset = Dataset(
        owner_user_id=owner_id,
        name=name,
        normalized_name=f"{name.casefold()}-{uuid4().hex}",
        description=None,
        kind=DatasetKind.DOCUMENT_COLLECTION,
        status=DatasetStatus.ACTIVE,
        state_version=0,
    )
    session.add(dataset)
    await session.flush()
    version = DatasetVersion(
        dataset_id=dataset.id,
        version_number=1,
        status=DatasetVersionStatus.READY,
        source_type=DatasetSourceType.UPLOAD,
        storage_key=f"integration/{uuid4().hex}",
        original_filename="handbook.txt",
        media_type="text/plain",
        size_bytes=32,
        sha256_digest=uuid4().hex * 2,
        document_count=1,
        chunk_count=0,
        schema_snapshot={"format": "plain_text"},
        lineage_snapshot={"source_type": "upload"},
        ingestion_options={},
        processing_summary={"document_count": 1},
        created_by_user_id=owner_id,
        state_version=1,
    )
    session.add(version)
    await session.flush()
    dataset.current_version_id = version.id
    document = DocumentRecord(
        dataset_version_id=version.id,
        document_number=1,
        title=title,
        source_filename="handbook.txt",
        media_type="text/plain",
        size_bytes=32,
        sha256_digest=uuid4().hex * 2,
        extracted_character_count=32,
        status=DocumentProcessingStatus.READY,
        extracted_text="Registered maintenance evidence.",
    )
    session.add(document)
    await session.flush()
    return version, document


async def _indexed_vector(
    session: AsyncSession,
    *,
    knowledge_base_id: UUID,
    build_id: UUID,
    version_id: UUID,
    document: DocumentRecord,
    embedding: tuple[float, ...],
    content: str,
) -> None:
    chunk = RAGIndexedChunk(
        knowledge_base_id=knowledge_base_id,
        index_build_id=build_id,
        document_id=document.id,
        dataset_version_id=version_id,
        chunk_number=0,
        content=content,
        content_hash=uuid4().hex * 2,
        character_count=len(content),
    )
    session.add(chunk)
    await session.flush()
    session.add(
        RAGChunkEmbedding(
            knowledge_base_id=knowledge_base_id,
            index_build_id=build_id,
            chunk_id=chunk.id,
            document_id=document.id,
            dataset_version_id=version_id,
            embedding_dimension=256,
            embedding=list(embedding),
            content_hash=chunk.content_hash,
        )
    )
    await session.flush()


def _unit_vector(index: int) -> tuple[float, ...]:
    values = [0.0] * 256
    values[index] = 1.0
    return tuple(values)


def _normalized_vector(first: float, second: float) -> tuple[float, ...]:
    values = [0.0] * 256
    values[0] = first
    values[1] = second
    return tuple(values)
