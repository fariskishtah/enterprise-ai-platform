"""Automated failure, resilience, and recovery contract tests."""

from collections.abc import Sequence
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from app.datasets.queue import DatasetProcessingQueue
from app.datasets.service import DatasetLimits, DatasetProcessor
from app.datasets.storage import LocalDatasetObjectStorage
from app.dependencies.datasets import get_dataset_queue
from app.dependencies.operational import OperationalProbe
from app.models.rag import RAGIndexBuildStatus
from app.models.user import UserRole
from app.rag.domain import GroundedAnswer, RetrievalResult
from app.rag.embeddings import DeterministicHashEmbeddingProvider
from app.rag.queue import RAGIndexQueue
from app.repositories.datasets import DatasetRepository
from app.repositories.rag import RAGRepository
from app.services.rag import RAGService, RAGUnavailableError
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import ai_api_client, auth_headers
from tests.test_rag_service import _seed_document


class FailingQueue(DatasetProcessingQueue, RAGIndexQueue):
    """Queue implementation that simulates Redis network failures."""

    def enqueue(self, _version_id: UUID) -> str:
        raise RedisConnectionError("Connection closed by peer")

    def enqueue_build(self, _build_id: UUID) -> str:
        raise RedisConnectionError("Connection closed by peer")


class FailingEmbeddingProvider:
    """Embedding provider that raises an operational exception."""

    @property
    def provider_name(self) -> str:
        return "failing"

    @property
    def model_name(self) -> str:
        return "test"

    @property
    def dimension(self) -> int:
        return 256

    def embed(self, _texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        raise RuntimeError("Embedding model service unreachable.")


class FailingGenerationProvider:
    """Generation provider that raises an operational exception."""

    @property
    def provider_name(self) -> str:
        return "failing"

    @property
    def model_name(self) -> str:
        return "test"

    def generate(
        self,
        *,
        question: str,  # noqa: ARG002
        evidence: Sequence[RetrievalResult],  # noqa: ARG002
        recent_history: Sequence[str],  # noqa: ARG002
    ) -> GroundedAnswer:
        raise RuntimeError("LLM generation provider timeout.")


def _limits() -> DatasetLimits:
    return DatasetLimits(
        upload_bytes=1024 * 1024,
        maximum_rows=100,
        maximum_columns=20,
        maximum_cell_characters=1000,
        maximum_document_characters=10_000,
        stale_after_seconds=60,
    )


@pytest.mark.anyio
async def test_redis_enqueue_failure_returns_safe_503(
    settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_dataset_queue] = lambda: FailingQueue()
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="resilience-redis-fail@example.com",
        )
        dataset = await client.post(
            "/ai/datasets",
            headers=headers,
            json={"name": "Redis Failure Test", "kind": "tabular"},
        )
        assert dataset.status_code == 201

        response = await client.post(
            f"/ai/datasets/{dataset.json()['id']}/versions",
            headers=headers,
            files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
        )
        assert response.status_code == 503
        body = response.json()
        assert "redis" not in str(body).lower()
        assert body["detail"] == "Dataset processing could not be queued."


@pytest.mark.anyio
async def test_operational_probe_reports_degraded_when_worker_offline() -> None:
    probe = OperationalProbe("redis://localhost:6379/0")
    fake_redis = AsyncMock()
    fake_redis.ping.return_value = True
    fake_redis.get.return_value = None  # No heartbeat written by worker
    probe._redis = fake_redis

    redis_status, worker_status, status = await probe.queue_and_worker()
    assert redis_status == "available"
    assert worker_status == "available"
    assert status == "unavailable"


@pytest.mark.anyio
async def test_embedding_provider_failure_marks_index_build_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seeded = await _seed_document(
            session,
            email="embed-fail@example.com",
            dataset_name="Embed fail docs",
            text="Operating manual content.",
        )
        repository = RAGRepository(session)
        service = RAGService(
            repository=repository,
            embedding_provider=FailingEmbeddingProvider(),
            generation_provider=AsyncMock(),
        )
        kb = await service.create_knowledge_base(
            owner_user_id=seeded.owner_id,
            name="Failing Embeddings KB",
            description=None,
            chunk_size=800,
            chunk_overlap=100,
        )
        await service.attach_dataset_version(
            knowledge_base_id=kb.knowledge_base.id,
            dataset_version_id=seeded.dataset_version_id,
            user_id=seeded.owner_id,
            is_admin=False,
        )
        build = await service.create_build(
            knowledge_base_id=kb.knowledge_base.id,
            user_id=seeded.owner_id,
            is_admin=False,
        )

        with pytest.raises(RAGUnavailableError):
            await service.process_build(build.id)

        updated_build = await repository.get_build(
            build_id=build.id, user_id=seeded.owner_id, is_admin=True
        )
        assert updated_build is not None
        assert updated_build.status == RAGIndexBuildStatus.FAILED
        assert updated_build.safe_error_message is not None


@pytest.mark.anyio
async def test_generation_provider_failure_handles_error_safely(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seeded = await _seed_document(
            session,
            email="gen-fail@example.com",
            dataset_name="Gen fail docs",
            text="Safety procedure manual content.",
        )
        repository = RAGRepository(session)
        service = RAGService(
            repository=repository,
            embedding_provider=DeterministicHashEmbeddingProvider(),
            generation_provider=FailingGenerationProvider(),
        )
        kb = await service.create_knowledge_base(
            owner_user_id=seeded.owner_id,
            name="Failing Generation KB",
            description=None,
            chunk_size=800,
            chunk_overlap=100,
        )
        await service.attach_dataset_version(
            knowledge_base_id=kb.knowledge_base.id,
            dataset_version_id=seeded.dataset_version_id,
            user_id=seeded.owner_id,
            is_admin=False,
        )
        build = await service.create_build(
            knowledge_base_id=kb.knowledge_base.id,
            user_id=seeded.owner_id,
            is_admin=False,
        )
        await service.process_build(build.id)

        conv = await service.create_conversation(
            owner_user_id=seeded.owner_id,
            is_admin=False,
            knowledge_base_id=kb.knowledge_base.id,
            title="Resilience Chat",
        )

        with pytest.raises(RAGUnavailableError):
            await service.submit_message(
                conversation_id=conv.id,
                user_id=seeded.owner_id,
                is_admin=False,
                content="Test failure handling query",
                idempotency_key="resilience-key-1",
            )


@pytest.mark.anyio
async def test_oversized_payload_rejection(
    settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="oversized-test@example.com",
        )
        dataset = await client.post(
            "/ai/datasets",
            headers=headers,
            json={"name": "Oversized Test", "kind": "tabular"},
        )
        assert dataset.status_code == 201

        # File size exceeds limit
        large_file = b"x" * (settings.dataset_upload_max_bytes + 1024)
        response = await client.post(
            f"/ai/datasets/{dataset.json()['id']}/versions",
            headers=headers,
            files={"file": ("too_large.csv", large_file, "text/csv")},
        )
        assert response.status_code in (413, 422)


@pytest.mark.anyio
async def test_stale_reconciliation_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with session_factory() as session:
        repository = DatasetRepository(session)
        processor = DatasetProcessor(
            repository=repository,
            storage=LocalDatasetObjectStorage(tmp_path / "datasets"),
            limits=_limits(),
        )
        mock_queue = AsyncMock()

        repaired_first = await processor.reconcile_stale(mock_queue)
        repaired_second = await processor.reconcile_stale(mock_queue)

        assert repaired_first == 0
        assert repaired_second == 0
