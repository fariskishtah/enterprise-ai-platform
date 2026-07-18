"""Authenticated background-job API integration tests."""

from pathlib import Path
from uuid import UUID

import pytest
from app.config.settings import Settings
from app.dependencies.services import (
    get_training_job_queue,
    get_training_job_service,
)
from app.ml.jobs import (
    TrainingJobQueuePersistenceError,
)
from app.models.user import UserRole
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import (
    ai_api_client,
    auth_headers,
    regression_training_payload,
)


class ApiFakeQueue:
    """Capture stable job identifiers submitted through the HTTP boundary."""

    def __init__(self) -> None:
        self.job_ids: list[UUID] = []

    def enqueue(self, training_job_id: UUID) -> str:
        self.job_ids.append(training_job_id)
        return f"api-message-{training_job_id}"


class PendingSubmissionService:
    """Submission double for post-enqueue identifier persistence failure."""

    async def submit(self, **_arguments: object) -> None:
        raise TrainingJobQueuePersistenceError("private database details")


@pytest.mark.anyio
async def test_background_job_submission_polling_idempotency_and_cancellation(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """The API returns 202, owner-scoped status, idempotency, and honest cancel."""
    queue = ApiFakeQueue()
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, application):
        application.dependency_overrides[get_training_job_queue] = lambda: queue
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="job-api@example.com",
        )
        idempotent_headers = {**headers, "Idempotency-Key": "api-stable-request"}
        submitted = await client.post(
            "/ai/training-jobs/random-forest/regression",
            headers=idempotent_headers,
            json=regression_training_payload(),
        )
        repeated = await client.post(
            "/ai/training-jobs/random-forest/regression",
            headers=idempotent_headers,
            json=regression_training_payload(),
        )
        job_id = submitted.json()["job_id"]
        polled = await client.get(
            f"/ai/training-jobs/{job_id}",
            headers=headers,
        )
        listed = await client.get("/ai/training-jobs", headers=headers)
        cancelled = await client.post(
            f"/ai/training-jobs/{job_id}/cancel",
            headers=headers,
        )
        duplicate_cancel = await client.post(
            f"/ai/training-jobs/{job_id}/cancel",
            headers=headers,
        )

    assert submitted.status_code == 202
    assert submitted.json() == {
        "job_id": job_id,
        "status": "queued",
        "submitted_at": submitted.json()["submitted_at"],
        "status_url": f"/ai/training-jobs/{job_id}",
    }
    assert repeated.status_code == 200
    assert repeated.json()["job_id"] == job_id
    assert queue.job_ids == [UUID(job_id)]
    assert polled.status_code == 200
    assert polled.json()["registered_model_version"] is None
    assert polled.json()["mlflow_run_id"] is None
    assert listed.json()["total"] == 1
    assert cancelled.json()["status"] == "cancelled"
    assert duplicate_cancel.status_code == 409


@pytest.mark.anyio
async def test_submission_message_persistence_failure_is_not_reported_as_accepted(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """An enqueued-but-unrecorded message maps to a sanitized operational error."""
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, application):
        application.dependency_overrides[get_training_job_service] = (
            PendingSubmissionService
        )
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="job-persistence-api@example.com",
        )
        response = await client.post(
            "/ai/training-jobs/random-forest/regression",
            headers=headers,
            json=regression_training_payload(),
        )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "The queued job requires operational reconciliation."
    )
    assert "database" not in response.text


@pytest.mark.anyio
async def test_job_management_rejects_operator_and_hides_other_engineer_jobs(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Operators cannot manage jobs and engineer ownership returns a safe 404."""
    queue = ApiFakeQueue()
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, application):
        application.dependency_overrides[get_training_job_queue] = lambda: queue
        owner_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="job-owner@example.com",
        )
        other_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="job-other@example.com",
        )
        operator_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="job-operator@example.com",
        )
        submitted = await client.post(
            "/ai/training-jobs/random-forest/regression",
            headers=owner_headers,
            json=regression_training_payload(),
        )
        job_id = submitted.json()["job_id"]
        hidden = await client.get(
            f"/ai/training-jobs/{job_id}",
            headers=other_headers,
        )
        forbidden_submit = await client.post(
            "/ai/training-jobs/random-forest/regression",
            headers=operator_headers,
            json=regression_training_payload(),
        )
        forbidden_list = await client.get(
            "/ai/training-jobs",
            headers=operator_headers,
        )

    assert hidden.status_code == 404
    assert forbidden_submit.status_code == 403
    assert forbidden_list.status_code == 403
