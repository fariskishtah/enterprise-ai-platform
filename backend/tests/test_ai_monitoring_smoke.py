"""Real local training, prediction-event, monitoring, and drift smoke coverage."""

from pathlib import Path
from uuid import UUID

import pytest
from app.config.settings import Settings
from app.ml.composition import (
    create_ai_model_registry,
    create_ai_tracked_training_service,
)
from app.ml.domain import TaskType
from app.ml.jobs import RandomForestRegressionJobSpec, random_forest_key
from app.ml.jobs.service import TrainingJobService
from app.ml.jobs.worker import (
    TrainingJobWorker,
    WorkerExecutionState,
    execute_tracked_training_specification,
)
from app.models.user import UserRole
from app.repositories.ai_governance import TrainingJobRepository
from app.repositories.ai_monitoring import PredictionMonitoringRepository
from app.repositories.users import UserRepository
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import (
    ai_api_client,
    auth_headers,
    regression_training_payload,
)


class SmokeQueue:
    """Record the UUID while the real worker executes in-process."""

    def __init__(self) -> None:
        self.job_id: UUID | None = None

    def enqueue(self, training_job_id: UUID) -> str:
        self.job_id = training_job_id
        return f"monitoring-smoke-{training_job_id}"


async def _engineer_id(
    session_factory: async_sessionmaker[AsyncSession],
    email: str,
) -> UUID:
    async with session_factory() as session:
        user = await UserRepository(session).get_by_email(email)
    assert user is not None
    return user.id


async def _train_background_version(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    requested_by_user_id: UUID,
) -> str:
    specification = RandomForestRegressionJobSpec(
        training_features=((0.0,), (1.0,), (2.0,), (3.0,)),
        training_targets=(0.0, 1.0, 2.0, 3.0),
        evaluation_features=((0.5,), (2.5,)),
        evaluation_targets=(0.5, 2.5),
        hyperparameters={"n_estimators": 3, "n_jobs": 1},
        random_seed=17,
        experiment_name="Monitoring Smoke",
        registered_model_name="ai_core_random_forest_regression",
        tags={"purpose": "monitoring-smoke"},
    )
    queue = SmokeQueue()
    async with session_factory() as session:
        submission = await TrainingJobService(
            repository=TrainingJobRepository(session),
            queue=queue,
            max_attempts=3,
        ).submit(
            requested_by_user_id=requested_by_user_id,
            key=random_forest_key(TaskType.REGRESSION),
            specification=specification,
            idempotency_key="monitoring-smoke",
        )
    registry = create_ai_model_registry(settings)
    tracked_service = create_ai_tracked_training_service(
        settings,
        model_registry=registry,
    )

    def assign_candidate_alias(name: str, version: str) -> None:
        registry.assign_alias(name, "candidate", version)

    worker = TrainingJobWorker(
        session_factory=session_factory,
        execute_specification=lambda persisted: (
            execute_tracked_training_specification(
                persisted,
                service=tracked_service,
                profile_bin_count=settings.monitoring_profile_bin_count,
            )
        ),
        assign_candidate_alias=assign_candidate_alias,
    )

    assert queue.job_id == submission.job.id
    assert await worker.execute(submission.job.id) is WorkerExecutionState.SUCCEEDED
    async with session_factory() as session:
        profile = await PredictionMonitoringRepository(session).get_reference_profile(
            specification.registered_model_name,
            "1",
        )
    assert profile is not None
    assert profile.training_job_id == submission.job.id
    return profile.model_version


async def _monitoring_requests(
    client: AsyncClient,
    *,
    headers: dict[str, str],
    model_version: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    model_name = "ai_core_random_forest_regression"
    prediction = await client.post(
        "/ai/predictions/random-forest/regression",
        headers={**headers, "X-Correlation-ID": "monitoring-smoke-1"},
        json={
            "registered_model_name": model_name,
            "version_or_alias": "candidate",
            "features": [[0.75], [2.75]],
        },
    )
    assert prediction.status_code == 200
    assert prediction.json()["model_version"] == model_version

    paths = (
        f"/ai/monitoring/models/{model_name}/versions/candidate/operations",
        f"/ai/monitoring/models/{model_name}/versions/candidate/data-quality",
        f"/ai/monitoring/models/{model_name}/versions/candidate/reference-profile",
        (
            f"/ai/monitoring/models/{model_name}/versions/candidate/drift"
            "?minimum_sample_count=1"
        ),
    )
    responses = [await client.get(path, headers=headers) for path in paths]
    assert all(response.status_code == 200 for response in responses)
    bodies: list[dict[str, object]] = [response.json() for response in responses]
    return bodies[0], bodies[1], bodies[2], bodies[3]


@pytest.mark.anyio
async def test_real_monitoring_and_drift_flow(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Use real MLflow, prediction, SQL repositories, profiles, and drift engine."""
    resolved_settings = settings.model_copy(
        update={
            "mlflow_tracking_uri": f"file:{tmp_path / 'mlruns'}",
            "model_artifact_root": str(tmp_path / "mlflow-artifacts"),
            "ai_artifact_root": str(tmp_path / "ai-artifacts"),
            "monitoring_min_sample_count": 1,
        },
    )
    async with ai_api_client(
        resolved_settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, _application):
        email = "monitoring-smoke@example.com"
        engineer_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email=email,
        )
        engineer_id = await _engineer_id(session_factory, email)
        model_version = await _train_background_version(
            settings=resolved_settings,
            session_factory=session_factory,
            requested_by_user_id=engineer_id,
        )
        operations, quality, reference, drift = await _monitoring_requests(
            client,
            headers=engineer_headers,
            model_version=model_version,
        )
        events = await client.get(
            "/ai/monitoring/prediction-events",
            headers=engineer_headers,
        )
        operator_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="monitoring-operator@example.com",
        )
        forbidden = await client.get(
            f"/ai/monitoring/prediction-events/{events.json()['items'][0]['event_id']}",
            headers=operator_headers,
        )
        invalid_window = await client.get(
            "/ai/monitoring/models/ai_core_random_forest_regression/versions/"
            "candidate/operations?start_at=2026-07-18T00:00:00Z&"
            "end_at=2026-07-17T00:00:00Z",
            headers=engineer_headers,
        )
        synchronous = await client.post(
            "/ai/training/random-forest/regression",
            headers=engineer_headers,
            json={
                **regression_training_payload(),
                "registered_model_name": "ai_core_random_forest_regression",
            },
        )
        assert synchronous.status_code == 201
        missing_profile = await client.get(
            "/ai/monitoring/models/ai_core_random_forest_regression/versions/"
            f"{synchronous.json()['registered_model_version']}/reference-profile",
            headers=engineer_headers,
        )

    assert operations["request_count"] == 1
    assert operations["success_count"] == 1
    assert operations["p50_latency_ms"] is not None
    assert operations["matched_event_count"] == 1
    assert operations["analyzed_event_count"] == 1
    assert operations["truncated"] is False
    assert operations["analysis_warning"] is None
    assert operations["instance_capture_failures_since_start"] == 0
    assert quality["request_count"] == 1
    assert quality["matched_event_count"] == 1
    assert quality["analyzed_event_count"] == 1
    assert quality["truncated"] is False
    assert quality["analysis_warning"] is None
    assert reference["model_version"] == model_version
    assert reference["source"] == "evaluation"
    assert drift["model_version"] == model_version
    assert drift["current_sample_count"] == 2
    assert drift["matched_event_count"] == 1
    assert drift["analyzed_event_count"] == 1
    assert drift["truncated"] is False
    assert drift["analysis_warning"] is None
    assert events.status_code == 200
    event = events.json()["items"][0]
    assert event["correlation_id"] == "monitoring-smoke-1"
    assert "requested_by_user_id" not in event
    assert "features" not in event
    assert "predictions" not in event
    assert forbidden.status_code == 403
    assert invalid_window.status_code == 422
    assert missing_profile.status_code == 404
    assert "profile" in missing_profile.json()["detail"].lower()
