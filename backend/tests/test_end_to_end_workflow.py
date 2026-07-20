"""Focused end-to-end coverage for the platform's primary local workflow."""

import asyncio
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

import pytest
from app.config.settings import Settings
from app.dependencies.services import get_training_job_queue
from app.ml.composition import (
    create_ai_model_registry,
    create_ai_tracked_training_service,
)
from app.ml.jobs.worker import (
    TrainingJobWorker,
    WorkerExecutionState,
    execute_tracked_training_specification,
)
from app.models.user import UserRole
from app.repositories.users import UserRepository
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import ai_api_client, regression_training_payload

PASSWORD = "ValidPassword1!"
MODEL_NAME = "e2e_random_forest_regression"
POLL_TIMEOUT_SECONDS = 90.0
POLL_INTERVAL_SECONDS = 0.25


class SingleJobQueue:
    """Capture exactly one queued UUID for the local in-process worker."""

    def __init__(self) -> None:
        self.job_id: UUID | None = None

    def enqueue(self, training_job_id: UUID) -> str:
        assert self.job_id is None, "E2E workflow must enqueue only one training job"
        self.job_id = training_job_id
        return f"e2e-{training_job_id}"


async def assert_created(response: object, resource: str) -> dict[str, object]:
    """Return a created API body or fail with useful response detail."""
    assert hasattr(response, "status_code") and hasattr(response, "json")
    assert response.status_code == 201, f"{resource} creation failed: {response.text}"
    return response.json()


async def create_manufacturing_path(
    client: AsyncClient,
    headers: dict[str, str],
) -> str:
    """Create the minimum hierarchy required for one sensor."""
    company = await assert_created(
        await client.post(
            "/companies",
            headers=headers,
            json={"name": "E2E Manufacturing"},
        ),
        "company",
    )
    factory = await assert_created(
        await client.post(
            "/factories",
            headers=headers,
            json={"company_id": company["id"], "name": "E2E Factory"},
        ),
        "factory",
    )
    machine = await assert_created(
        await client.post(
            "/machines",
            headers=headers,
            json={"factory_id": factory["id"], "name": "E2E Machine"},
        ),
        "machine",
    )
    sensor = await assert_created(
        await client.post(
            "/sensors",
            headers=headers,
            json={
                "machine_id": machine["id"],
                "name": "E2E Temperature",
                "sensor_type": "temperature",
                "unit": "celsius",
                "sampling_rate": 1.0,
                "min_value": 0.0,
                "max_value": 100.0,
            },
        ),
        "sensor",
    )
    return str(sensor["id"])


async def poll_job(
    client: AsyncClient,
    status_url: str,
    headers: dict[str, str],
) -> dict[str, object]:
    """Poll one job to a terminal state within the fixed E2E budget."""
    deadline = monotonic() + POLL_TIMEOUT_SECONDS
    snapshots: list[str] = []
    while monotonic() < deadline:
        response = await client.get(status_url, headers=headers)
        assert response.status_code == 200, f"job polling failed: {response.text}"
        body = response.json()
        snapshots.append(
            f"{body['status']}(attempt={body['attempt_count']}, "
            f"error={body['error_code']})"
        )
        if body["status"] in {"succeeded", "failed", "cancelled"}:
            assert (
                body["status"] == "succeeded"
            ), "training job did not succeed; recent status summary: " + " -> ".join(
                snapshots[-8:]
            )
            return body
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
    pytest.fail(
        "training job exceeded 90s; recent status summary: "
        + " -> ".join(snapshots[-8:])
    )


@pytest.mark.anyio
async def test_primary_platform_workflow_end_to_end(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Exercise auth, manufacturing, training, prediction, and monitoring."""
    resolved_settings = settings.model_copy(
        update={
            "mlflow_tracking_uri": f"file:{tmp_path / 'mlruns'}",
            "model_artifact_root": str(tmp_path / "mlflow-artifacts"),
            "ai_artifact_root": str(tmp_path / "ai-artifacts"),
            "monitoring_min_sample_count": 1,
        }
    )
    queue = SingleJobQueue()
    email = f"e2e-{uuid4()}@example.com"

    async with ai_api_client(
        resolved_settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, application):
        application.dependency_overrides[get_training_job_queue] = lambda: queue

        registered = await client.post(
            "/auth/register",
            json={"email": email, "password": PASSWORD},
        )
        assert registered.status_code == 201, registered.text
        async with session_factory() as session:
            user = await UserRepository(session).get_by_email(email)
            assert user is not None
            user.role = UserRole.ENGINEER
            await session.commit()

        logged_in = await client.post(
            "/auth/login",
            json={"email": email, "password": PASSWORD},
        )
        assert logged_in.status_code == 200, logged_in.text
        headers = {
            "Authorization": f"Bearer {logged_in.json()['access_token']}",
            "X-Request-ID": "e2e-workflow-request",
        }

        sensor_id = await create_manufacturing_path(client, headers)
        for minute, value in enumerate((10.0, 20.0, 30.0, 40.0)):
            reading = await client.post(
                "/sensor-readings",
                headers=headers,
                json={
                    "sensor_id": sensor_id,
                    "timestamp": f"2026-01-01T00:0{minute}:00Z",
                    "value": value,
                    "quality": "GOOD",
                    "source": "API",
                },
            )
            assert reading.status_code == 201, reading.text
            assert reading.headers["X-Request-ID"] == "e2e-workflow-request"

        training_payload = regression_training_payload()
        training_payload["registered_model_name"] = MODEL_NAME
        submitted = await client.post(
            "/ai/training-jobs/random-forest/regression",
            headers={**headers, "Idempotency-Key": "e2e-single-training-job"},
            json=training_payload,
        )
        assert submitted.status_code == 202, submitted.text
        submission = submitted.json()
        assert queue.job_id == UUID(submission["job_id"])

        registry = create_ai_model_registry(resolved_settings)
        tracked_service = create_ai_tracked_training_service(
            resolved_settings,
            model_registry=registry,
        )
        worker = TrainingJobWorker(
            session_factory=session_factory,
            execute_specification=lambda specification: (
                execute_tracked_training_specification(
                    specification,
                    service=tracked_service,
                    profile_bin_count=resolved_settings.monitoring_profile_bin_count,
                )
            ),
            assign_candidate_alias=lambda name, version: registry.assign_alias(
                name, "candidate", version
            ),
        )
        worker_task = asyncio.create_task(worker.execute(queue.job_id))
        completed = await poll_job(client, submission["status_url"], headers)
        assert await worker_task is WorkerExecutionState.SUCCEEDED

        version = str(completed["registered_model_version"])
        model = await client.get(
            f"/ai/models/{MODEL_NAME}/versions/{version}",
            headers=headers,
        )
        assert model.status_code == 200, model.text
        assert model.json()["model_version"] == version

        correlation_id = "e2e-prediction-correlation"
        prediction = await client.post(
            "/ai/predictions/random-forest/regression",
            headers={**headers, "X-Correlation-ID": correlation_id},
            json={
                "registered_model_name": MODEL_NAME,
                "version_or_alias": version,
                "features": [[2.25]],
            },
        )
        assert prediction.status_code == 200, prediction.text
        prediction_body = prediction.json()
        assert prediction_body["model_name"] == MODEL_NAME
        assert prediction_body["model_version"] == version
        assert prediction_body["trainer_key"] == {
            "algorithm": "random_forest",
            "task_type": "regression",
        }
        assert len(prediction_body["predictions"]) == 1
        assert isinstance(prediction_body["predictions"][0], float)

        events = await client.get(
            "/ai/monitoring/prediction-events",
            headers=headers,
            params={
                "registered_model_name": MODEL_NAME,
                "resolved_model_version": version,
                "limit": 1,
            },
        )
        assert events.status_code == 200, events.text
        event_page = events.json()
        assert event_page["total"] == 1
        event = event_page["items"][0]
        assert event["status"] == "succeeded"
        assert event["correlation_id"] == correlation_id
        assert event["resolved_model_version"] == version
        assert event["row_count"] == 1
        assert event["feature_count"] == 1
