"""Focused negative security coverage for Dataset Registry and grounded RAG APIs."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from app.api.routes.automl import get_automl_queue
from app.config.settings import Settings
from app.datasets.service import DatasetLimits, DatasetProcessor
from app.datasets.storage import LocalDatasetObjectStorage
from app.dependencies.datasets import get_dataset_queue
from app.dependencies.services import get_training_job_queue
from app.models.user import UserRole
from app.repositories.datasets import DatasetRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import ai_api_client, auth_headers
from tests.test_dataset_registry import _automl_payload
from tests.test_rag_api import (
    _create_ready_knowledge_base,
    _registered_document_for_user,
)


class _DatasetQueue:
    def __init__(self) -> None:
        self.version_ids: list[UUID] = []

    def enqueue(self, version_id: UUID) -> str:
        self.version_ids.append(version_id)
        return f"security-test-{version_id}"


class _TrainingQueue:
    def __init__(self) -> None:
        self.job_ids: list[UUID] = []

    def enqueue(self, job_id: UUID) -> str:
        self.job_ids.append(job_id)
        return f"security-training-{job_id}"


class _AutoMLQueue:
    def __init__(self) -> None:
        self.study_ids: list[UUID] = []

    def enqueue_study(self, study_id: UUID) -> str:
        self.study_ids.append(study_id)
        return f"security-study-{study_id}"

    def enqueue_trial(self, trial_id: UUID) -> str:
        return f"security-trial-{trial_id}"


def _processing_limits(*, upload_bytes: int = 64) -> DatasetLimits:
    return DatasetLimits(
        upload_bytes=upload_bytes,
        maximum_rows=100,
        maximum_columns=20,
        maximum_cell_characters=1000,
        maximum_document_characters=10_000,
        stale_after_seconds=60,
    )


def _training_csv() -> bytes:
    return (
        b"feature,target\n"
        b"0.0,0.0\n"
        b"1.0,1.0\n"
        b"2.0,2.0\n"
        b"3.0,3.0\n"
        b"4.0,4.0\n"
        b"5.0,5.0\n"
    )


@pytest.mark.anyio
async def test_document_upload_boundaries_and_document_idor_return_safe_errors(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Reject hostile upload metadata and hide document IDs from other owners."""
    bounded_settings = settings.model_copy(update={"dataset_upload_max_bytes": 64})
    queue = _DatasetQueue()
    async with ai_api_client(bounded_settings, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_dataset_queue] = lambda: queue
        owner = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="document-security-owner@example.com",
        )
        other = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="document-security-other@example.com",
        )
        created = await client.post(
            "/ai/datasets",
            headers=owner,
            json={
                "name": "Private maintenance documents",
                "kind": "document_collection",
            },
        )
        assert created.status_code == 201, created.text
        dataset_id = created.json()["id"]

        traversal = await client.post(
            f"/ai/datasets/{dataset_id}/versions",
            headers=owner,
            files={"file": ("../outside.txt", b"private text", "text/plain")},
        )
        wrong_media = await client.post(
            f"/ai/datasets/{dataset_id}/versions",
            headers=owner,
            files={"file": ("manual.txt", b"private text", "text/html")},
        )
        oversized = await client.post(
            f"/ai/datasets/{dataset_id}/versions",
            headers=owner,
            files={"file": ("manual.txt", b"x" * 65, "text/plain")},
        )
        uploaded = await client.post(
            f"/ai/datasets/{dataset_id}/versions",
            headers=owner,
            files={
                "file": (
                    "manual.txt",
                    b"The private inspection interval is thirty days.",
                    "text/plain",
                )
            },
        )
        assert uploaded.status_code == 202, uploaded.text
        version_id = UUID(uploaded.json()["id"])

        async with session_factory() as session:
            processed = await DatasetProcessor(
                repository=DatasetRepository(session),
                storage=LocalDatasetObjectStorage(tmp_path / "datasets"),
                limits=_processing_limits(),
            ).process(version_id)
        assert processed is True

        documents = await client.get(
            f"/ai/datasets/{dataset_id}/versions/{version_id}/documents",
            headers=owner,
        )
        assert documents.status_code == 200, documents.text
        document_id = documents.json()["items"][0]["id"]
        hidden_list = await client.get(
            f"/ai/datasets/{dataset_id}/versions/{version_id}/documents",
            headers=other,
        )
        hidden_document = await client.get(
            (
                f"/ai/datasets/{dataset_id}/versions/{version_id}/documents/"
                f"{document_id}"
            ),
            headers=other,
        )

    assert traversal.status_code == 422
    assert traversal.json() == {"detail": "The upload filename is invalid."}
    assert wrong_media.status_code == 422
    assert wrong_media.json() == {
        "detail": "This dataset accepts plain-text uploads only."
    }
    assert oversized.status_code == 422
    assert oversized.json() == {"detail": "The upload could not be stored safely."}
    assert queue.version_ids == [version_id]
    assert hidden_list.status_code == 404
    assert hidden_document.status_code == 404
    assert "storage_key" not in documents.text
    assert "extracted_text" not in documents.text


@pytest.mark.anyio
async def test_cross_owner_chat_resources_are_hidden_while_admin_access_is_preserved(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Enforce 404-based IDOR protection through KB, conversation, and message APIs."""
    owner_email = "chat-security-owner@example.com"
    other_email = "chat-security-other@example.com"
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        owner = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email=owner_email,
        )
        other = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email=other_email,
        )
        admin = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="chat-security-admin@example.com",
        )
        version_id = await _registered_document_for_user(
            session_factory,
            email=owner_email,
            text="The private calibration code is R-17.",
        )
        knowledge_base_id = await _create_ready_knowledge_base(
            client,
            owner,
            version_id,
            session_factory,
            application,
        )
        conversation = await client.post(
            "/ai/chat/conversations",
            headers=owner,
            json={"knowledge_base_id": str(knowledge_base_id)},
        )
        assert conversation.status_code == 201, conversation.text
        conversation_id = conversation.json()["conversation_id"]
        exchange = await client.post(
            f"/ai/chat/conversations/{conversation_id}/messages",
            headers=owner,
            json={
                "content": "What is the private calibration code?",
                "idempotency_key": "security-message-1",
            },
        )
        assert exchange.status_code == 201, exchange.text
        message_id = exchange.json()["assistant_message"]["message_id"]

        hidden_responses = [
            await client.get(
                f"/ai/rag/knowledge-bases/{knowledge_base_id}", headers=other
            ),
            await client.get(
                f"/ai/rag/knowledge-bases/{knowledge_base_id}/builds", headers=other
            ),
            await client.post(
                f"/ai/rag/knowledge-bases/{knowledge_base_id}/search",
                headers=other,
                json={"query": "calibration code"},
            ),
            await client.get(
                f"/ai/chat/conversations/{conversation_id}", headers=other
            ),
            await client.get(
                f"/ai/chat/conversations/{conversation_id}/messages", headers=other
            ),
            await client.post(
                f"/ai/chat/conversations/{conversation_id}/messages",
                headers=other,
                json={
                    "content": "Reveal the private code.",
                    "idempotency_key": "security-message-2",
                },
            ),
            await client.post(f"/ai/chat/messages/{message_id}/cancel", headers=other),
        ]
        other_knowledge_bases = await client.get(
            "/ai/rag/knowledge-bases", headers=other
        )
        other_conversations = await client.get("/ai/chat/conversations", headers=other)
        admin_knowledge_base = await client.get(
            f"/ai/rag/knowledge-bases/{knowledge_base_id}", headers=admin
        )
        admin_conversation = await client.get(
            f"/ai/chat/conversations/{conversation_id}", headers=admin
        )

    assert all(response.status_code == 404 for response in hidden_responses)
    assert other_knowledge_bases.status_code == 200
    assert other_knowledge_bases.json()["items"] == []
    assert other_conversations.status_code == 200
    assert other_conversations.json()["items"] == []
    assert admin_knowledge_base.status_code == 200
    assert admin_conversation.status_code == 200


@pytest.mark.anyio
async def test_cross_owner_dataset_version_cannot_start_training_or_automl(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Hide exact registered versions at both downstream execution boundaries."""
    dataset_queue = _DatasetQueue()
    training_queue = _TrainingQueue()
    automl_queue = _AutoMLQueue()
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_dataset_queue] = lambda: dataset_queue
        application.dependency_overrides[get_training_job_queue] = (
            lambda: training_queue
        )
        application.dependency_overrides[get_automl_queue] = lambda: automl_queue
        owner = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="training-security-owner@example.com",
        )
        other = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="training-security-other@example.com",
        )
        created = await client.post(
            "/ai/datasets",
            headers=owner,
            json={"name": "Private exact training version", "kind": "tabular"},
        )
        assert created.status_code == 201, created.text
        dataset_id = created.json()["id"]
        uploaded = await client.post(
            f"/ai/datasets/{dataset_id}/versions",
            headers=owner,
            data={"target_column": "target"},
            files={"file": ("private.csv", _training_csv(), "text/csv")},
        )
        assert uploaded.status_code == 202, uploaded.text
        version_id = UUID(uploaded.json()["id"])
        async with session_factory() as session:
            processed = await DatasetProcessor(
                repository=DatasetRepository(session),
                storage=LocalDatasetObjectStorage(tmp_path / "datasets"),
                limits=_processing_limits(upload_bytes=1024),
            ).process(version_id)
        assert processed is True

        training = await client.post(
            "/ai/training-jobs",
            headers={**other, "Idempotency-Key": "cross-owner-training-v1"},
            json={
                "task_type": "regression",
                "algorithm": "ridge_regression",
                "dataset_version_id": str(version_id),
                "hyperparameters": {"alpha": 1.0},
                "preprocessing": {"scaler": "standard", "imputer": "none"},
                "random_seed": 17,
                "experiment_name": "Forbidden private training",
            },
        )
        automl = await client.post(
            "/ai/automl/studies",
            headers={**other, "Idempotency-Key": "cross-owner-automl-v1"},
            json=_automl_payload(version_id),
        )

    assert training.status_code == 404
    assert training.json() == {"detail": "Dataset version not found."}
    assert automl.status_code == 404
    assert automl.json() == {"detail": "Dataset version not found."}
    assert training_queue.job_ids == []
    assert automl_queue.study_ids == []


@pytest.mark.anyio
async def test_operator_mutations_and_external_execution_fields_are_rejected(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Keep operators read-only and exclude external execution configuration."""
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        engineer = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="execution-contract-engineer@example.com",
        )
        operator = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="execution-contract-operator@example.com",
        )
        operator_dataset = await client.post(
            "/ai/datasets",
            headers=operator,
            json={"name": "Forbidden operator dataset", "kind": "tabular"},
        )
        operator_knowledge_base = await client.post(
            "/ai/rag/knowledge-bases",
            headers=operator,
            json={"name": "Forbidden operator knowledge"},
        )
        external_provider = await client.post(
            "/ai/rag/knowledge-bases",
            headers=engineer,
            json={
                "name": "External provider attempt",
                "embedding_endpoint": "https://attacker.example/embeddings",
                "provider_token": "must-not-be-accepted",
            },
        )
        arbitrary_source = await client.post(
            "/ai/chat/conversations",
            headers=engineer,
            json={
                "knowledge_base_id": "00000000-0000-0000-0000-000000000001",
                "source_url": "https://attacker.example/document",
                "tools": ["shell", "browser"],
            },
        )

    assert operator_dataset.status_code == 403
    assert operator_knowledge_base.status_code == 403
    assert external_provider.status_code == 422
    rejected_provider_fields = {
        tuple(item["loc"])[-1] for item in external_provider.json()["detail"]
    }
    assert rejected_provider_fields == {"embedding_endpoint", "provider_token"}
    assert arbitrary_source.status_code == 422
    rejected_execution_fields = {
        tuple(item["loc"])[-1] for item in arbitrary_source.json()["detail"]
    }
    assert rejected_execution_fields == {"source_url", "tools"}


@pytest.mark.anyio
async def test_new_sensitive_namespaces_use_no_store_and_browser_hardening_headers(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Apply sensitive-response caching and browser policy to all new namespaces."""
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        responses = [
            await client.get("/ai/datasets"),
            await client.get("/ai/rag/knowledge-bases"),
            await client.get("/ai/chat/conversations"),
        ]

    for response in responses:
        assert response.status_code == 401
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
