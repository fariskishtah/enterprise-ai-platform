"""Dataset Registry storage, ingestion, ownership, and lineage tests."""

from __future__ import annotations

from datetime import timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from app.api.routes.automl import get_automl_queue
from app.datasets.service import DatasetLimits, DatasetProcessor
from app.datasets.storage import DatasetStorageError, LocalDatasetObjectStorage
from app.dependencies.datasets import get_dataset_queue
from app.dependencies.services import get_training_job_queue
from app.models.ai_governance import TrainingJob
from app.models.automl import AutoMLStudy
from app.models.datasets import DatasetUsageReference, DatasetVersion
from app.models.user import UserRole
from app.repositories.datasets import DatasetRepository
from app.utils.security import utc_now
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import ai_api_client, auth_headers


class CapturingDatasetQueue:
    def __init__(self) -> None:
        self.ids: list[UUID] = []

    def enqueue(self, version_id: UUID) -> str:
        self.ids.append(version_id)
        return f"dataset-{version_id}"


class CapturingTrainingQueue:
    def __init__(self) -> None:
        self.ids: list[UUID] = []

    def enqueue(self, job_id: UUID) -> str:
        self.ids.append(job_id)
        return f"training-{job_id}"


class CapturingAutoMLQueue:
    def enqueue_study(self, study_id: UUID) -> str:
        return f"study-{study_id}"

    def enqueue_trial(self, trial_id: UUID) -> str:
        return f"trial-{trial_id}"


def _limits() -> DatasetLimits:
    return DatasetLimits(
        upload_bytes=1024 * 1024,
        maximum_rows=100,
        maximum_columns=20,
        maximum_cell_characters=1000,
        maximum_document_characters=10_000,
        stale_after_seconds=60,
    )


def _csv() -> bytes:
    return b"feature,target\n0.0,0.0\n1.0,1.0\n2.0,2.0\n3.0,3.0\n4.0,4.0\n5.0,5.0\n"


@pytest.mark.anyio
async def test_dataset_registry_is_company_scoped_and_processes_bounded_csv(
    settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    queue = CapturingDatasetQueue()
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_dataset_queue] = lambda: queue
        owner = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="dataset-owner@example.com",
        )
        other = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="dataset-other@example.com",
        )
        operator = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="dataset-operator@example.com",
        )
        created = await client.post(
            "/ai/datasets",
            headers=owner,
            json={
                "name": "Deterministic Training Data",
                "description": "Tiny owned fixture",
                "kind": "tabular",
            },
        )
        dataset_id = created.json()["id"]
        duplicate = await client.post(
            "/ai/datasets",
            headers=owner,
            json={"name": "deterministic  training data", "kind": "tabular"},
        )
        hidden = await client.get(f"/ai/datasets/{dataset_id}", headers=other)
        forbidden = await client.get("/ai/datasets", headers=operator)
        uploaded = await client.post(
            f"/ai/datasets/{dataset_id}/versions",
            headers=owner,
            data={"target_column": "target", "evaluation_fraction": "0.33"},
            files={"file": ("bounded.csv", _csv(), "text/csv")},
        )
        version_id = uploaded.json()["id"]
        pre_process = await client.get(
            f"/ai/datasets/{dataset_id}/versions/{version_id}", headers=owner
        )

        assert queue.ids == [UUID(version_id)]
        async with session_factory() as session:
            processed = await DatasetProcessor(
                repository=DatasetRepository(session),
                storage=LocalDatasetObjectStorage(tmp_path / "datasets"),
                limits=_limits(),
            ).process(UUID(version_id))
        detail = await client.get(
            f"/ai/datasets/{dataset_id}/versions/{version_id}", headers=owner
        )
        schema = await client.get(
            f"/ai/datasets/{dataset_id}/versions/{version_id}/schema",
            headers=owner,
        )
        hidden_version = await client.get(
            f"/ai/datasets/{dataset_id}/versions/{version_id}", headers=other
        )

    assert created.status_code == 201
    assert duplicate.status_code == 409
    assert hidden.status_code == 200
    assert forbidden.status_code == 403
    assert uploaded.status_code == 202
    assert pre_process.json()["status"] == "pending"
    assert processed is True
    assert detail.json()["status"] == "ready"
    assert detail.json()["row_count"] == 6
    assert detail.json()["column_count"] == 2
    assert detail.json()["schema_snapshot"]["target_column"] == "target"
    assert "storage_key" not in detail.text
    assert schema.json()["schema_snapshot"]["columns"][0]["name"] == "feature"
    assert hidden_version.status_code == 200


@pytest.mark.anyio
async def test_registered_version_drives_training_and_automl_exact_lineage(
    settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    dataset_queue = CapturingDatasetQueue()
    training_queue = CapturingTrainingQueue()
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_dataset_queue] = lambda: dataset_queue
        application.dependency_overrides[get_training_job_queue] = lambda: (
            training_queue
        )
        application.dependency_overrides[get_automl_queue] = CapturingAutoMLQueue
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="dataset-training@example.com",
        )
        created = await client.post(
            "/ai/datasets",
            headers=headers,
            json={"name": "Registry Lineage", "kind": "tabular"},
        )
        dataset_id = created.json()["id"]
        uploaded = await client.post(
            f"/ai/datasets/{dataset_id}/versions",
            headers=headers,
            data={"target_column": "target"},
            files={"file": ("lineage.csv", _csv(), "text/csv")},
        )
        version_id = UUID(uploaded.json()["id"])
        async with session_factory() as session:
            await DatasetProcessor(
                repository=DatasetRepository(session),
                storage=LocalDatasetObjectStorage(tmp_path / "datasets"),
                limits=_limits(),
            ).process(version_id)

        training = await client.post(
            "/ai/training-jobs",
            headers={**headers, "Idempotency-Key": "dataset-training-v1"},
            json={
                "task_type": "regression",
                "algorithm": "ridge_regression",
                "dataset_version_id": str(version_id),
                "hyperparameters": {"alpha": 1.0},
                "preprocessing": {"scaler": "standard", "imputer": "none"},
                "random_seed": 17,
                "experiment_name": "Registry Training",
            },
        )
        automl = await client.post(
            "/ai/automl/studies",
            headers={**headers, "Idempotency-Key": "dataset-automl-v1"},
            json=_automl_payload(version_id),
        )

    assert training.status_code == 202, training.text
    assert automl.status_code == 202, automl.text
    async with session_factory() as session:
        job = await session.get(TrainingJob, UUID(training.json()["job_id"]))
        study = await session.get(AutoMLStudy, UUID(automl.json()["study_id"]))
        references = (
            await session.scalars(
                select(DatasetUsageReference).where(
                    DatasetUsageReference.dataset_version_id == version_id
                )
            )
        ).all()
    assert job is not None and job.dataset_version_id == version_id
    assert job.specification["dataset_version_id"] == str(version_id)
    assert job.specification["dataset_schema_snapshot"]["target_column"] == "target"
    assert study is not None and study.dataset_version_id == version_id
    assert study.data_specification["dataset_version_id"] == str(version_id)
    assert {item.usage_type for item in references} == {
        "automl_study",
        "training_job",
    }


@pytest.mark.anyio
async def test_out_of_order_processing_never_moves_current_version_backwards(
    settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    queue = CapturingDatasetQueue()
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_dataset_queue] = lambda: queue
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="dataset-ordering@example.com",
        )
        created = await client.post(
            "/ai/datasets",
            headers=headers,
            json={"name": "Concurrent version ordering", "kind": "tabular"},
        )
        dataset_id = created.json()["id"]
        first = await client.post(
            f"/ai/datasets/{dataset_id}/versions",
            headers=headers,
            data={"target_column": "target"},
            files={"file": ("first.csv", _csv(), "text/csv")},
        )
        second_payload = _csv().replace(b"5.0,5.0", b"6.0,6.0")
        second = await client.post(
            f"/ai/datasets/{dataset_id}/versions",
            headers=headers,
            data={"target_column": "target"},
            files={"file": ("second.csv", second_payload, "text/csv")},
        )
        first_id = UUID(first.json()["id"])
        second_id = UUID(second.json()["id"])

        async with session_factory() as session:
            processor = DatasetProcessor(
                repository=DatasetRepository(session),
                storage=LocalDatasetObjectStorage(tmp_path / "datasets"),
                limits=_limits(),
            )
            assert await processor.process(second_id) is True
            assert await processor.process(first_id) is True

        detail = await client.get(f"/ai/datasets/{dataset_id}", headers=headers)

    assert first.status_code == second.status_code == 202
    assert detail.status_code == 200
    assert detail.json()["current_version_id"] == str(second_id)


def test_local_dataset_storage_rejects_paths_and_oversized_writes(
    tmp_path: Path,
) -> None:
    storage = LocalDatasetObjectStorage(tmp_path / "objects")
    with pytest.raises(DatasetStorageError):
        storage.read("../outside", maximum_bytes=100)
    with pytest.raises(DatasetStorageError):
        storage.write(BytesIO(b"x" * 101), maximum_bytes=100)
    assert list((tmp_path / "objects").rglob(".upload-*")) == []


@pytest.mark.anyio
async def test_retry_pending_dataset_is_recovered_by_reconciliation(
    settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    initial_queue = CapturingDatasetQueue()
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_dataset_queue] = lambda: initial_queue
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="dataset-retry-reconciliation@example.com",
        )
        dataset = await client.post(
            "/ai/datasets",
            headers=headers,
            json={"name": "Retry reconciliation", "kind": "tabular"},
        )
        uploaded = await client.post(
            f"/ai/datasets/{dataset.json()['id']}/versions",
            headers=headers,
            data={"target_column": "target"},
            files={"file": ("retry.csv", _csv(), "text/csv")},
        )
    version_id = UUID(uploaded.json()["id"])

    async with session_factory() as session:
        repository = DatasetRepository(session)
        claimed = await repository.claim_version(version_id)
        assert claimed is not None
        released = await repository.release_version_for_retry(
            version_id,
            expected_version=claimed.state_version,
            safe_error_message="Temporary storage failure.",
        )
        assert released
        await session.execute(
            update(DatasetVersion)
            .where(DatasetVersion.id == version_id)
            .values(
                created_at=utc_now() - timedelta(hours=1),
                last_enqueued_at=utc_now() - timedelta(hours=1),
            )
        )
        await repository.commit()

        recovery_queue = CapturingDatasetQueue()
        repaired = await DatasetProcessor(
            repository=repository,
            storage=LocalDatasetObjectStorage(tmp_path / "datasets"),
            limits=_limits(),
        ).reconcile_stale(recovery_queue)

    assert repaired == 1
    assert recovery_queue.ids == [version_id]


@pytest.mark.anyio
async def test_archive_blocks_active_processing_and_active_rag_references(
    settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    queue = CapturingDatasetQueue()
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_dataset_queue] = lambda: queue
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="dataset-archive-guard@example.com",
        )
        created = await client.post(
            "/ai/datasets",
            headers=headers,
            json={"name": "Referenced documents", "kind": "document_collection"},
        )
        dataset_id = created.json()["id"]
        uploaded = await client.post(
            f"/ai/datasets/{dataset_id}/versions",
            headers=headers,
            files={
                "file": (
                    "guard.txt",
                    b"The safety guard must remain attached.",
                    "text/plain",
                )
            },
        )
        version_id = UUID(uploaded.json()["id"])
        processing_conflict = await client.post(
            f"/ai/datasets/{dataset_id}/archive", headers=headers
        )

        async with session_factory() as session:
            assert await DatasetProcessor(
                repository=DatasetRepository(session),
                storage=LocalDatasetObjectStorage(tmp_path / "datasets"),
                limits=_limits(),
            ).process(version_id)

        knowledge_base = await client.post(
            "/ai/rag/knowledge-bases",
            headers=headers,
            json={"name": "Archive guard knowledge"},
        )
        knowledge_base_id = knowledge_base.json()["knowledge_base_id"]
        attached = await client.post(
            f"/ai/rag/knowledge-bases/{knowledge_base_id}/dataset-versions",
            headers=headers,
            json={"dataset_version_id": str(version_id)},
        )
        reference_conflict = await client.post(
            f"/ai/datasets/{dataset_id}/archive", headers=headers
        )
        archived_kb = await client.post(
            f"/ai/rag/knowledge-bases/{knowledge_base_id}/archive", headers=headers
        )
        archived_dataset = await client.post(
            f"/ai/datasets/{dataset_id}/archive", headers=headers
        )

    assert processing_conflict.status_code == 409
    assert attached.status_code == 201
    assert reference_conflict.status_code == 409
    assert archived_kb.status_code == 200
    assert archived_dataset.status_code == 200


def _automl_payload(version_id: UUID) -> dict[str, object]:
    return {
        "task_type": "regression",
        "primary_metric": "rmse",
        "metric_direction": "minimize",
        "random_seed": 19,
        "plugin_ids": ["ridge_regression"],
        "plugin_search_spaces": [
            {
                "plugin_id": "ridge_regression",
                "task_type": "regression",
                "parameters": [
                    {
                        "name": "alpha",
                        "kind": "float",
                        "low": 0.001,
                        "high": 10.0,
                        "default": 1.0,
                        "log_scale": True,
                    },
                    {
                        "name": "fit_intercept",
                        "kind": "categorical",
                        "choices": [True, False],
                        "default": True,
                    },
                ],
                "probability_support": False,
            }
        ],
        "data": {"dataset_version_id": str(version_id)},
        "budget": {
            "trial_budget": 2,
            "time_budget_seconds": 60,
            "per_trial_timeout_seconds": 30,
            "max_concurrent_trials": 1,
            "cross_validation_folds": 2,
        },
    }
