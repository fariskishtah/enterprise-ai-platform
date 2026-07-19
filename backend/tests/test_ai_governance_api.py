"""Authenticated background-job and promotion API integration tests."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.config.settings import Settings
from app.dependencies.services import (
    get_model_promotion_service,
    get_training_job_queue,
    get_training_job_service,
)
from app.ml.domain import TaskType
from app.ml.jobs import (
    RandomForestRegressionJobSpec,
    TrainingJobQueuePersistenceError,
    random_forest_key,
)
from app.ml.promotion import (
    ModelPromotionRequest,
    ModelPromotionResult,
    PromotionAuditFinalizationError,
)
from app.ml.registry import ModelRegistryError
from app.models.user import UserRole
from app.repositories.ai_governance import TrainingJobRepository
from app.repositories.users import UserRepository
from app.utils.security import utc_now
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


class FailingPromotionService:
    """External-failure double for sanitized promotion transport behavior."""

    async def promote(
        self,
        request: ModelPromotionRequest,
        *,
        requester_role: UserRole,
    ) -> ModelPromotionResult:
        _ = (request, requester_role)
        raise ModelRegistryError("private registry host and credential details")


class PendingSubmissionService:
    """Submission double for post-enqueue identifier persistence failure."""

    async def submit(self, **_arguments: object) -> None:
        raise TrainingJobQueuePersistenceError("private database details")


class FailingPromotionFinalizationService:
    """Promotion double for alias-success/audit-finalization transport behavior."""

    async def promote(
        self,
        request: ModelPromotionRequest,
        *,
        requester_role: UserRole,
    ) -> ModelPromotionResult:
        _ = (request, requester_role)
        raise PromotionAuditFinalizationError("private database details")


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


@pytest.mark.anyio
async def test_real_promotion_api_and_champion_prediction_flow(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """A successful version moves challenger to champion and remains predictable."""
    resolved_settings = settings.model_copy(
        update={"promotion_regression_min_r2": -100.0},
    )
    email = "promotion-api@example.com"
    async with ai_api_client(
        resolved_settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, _application):
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email=email,
        )
        trained = await client.post(
            "/ai/training/random-forest/regression",
            headers=headers,
            json=regression_training_payload(),
        )
        assert trained.status_code == 201
        training_body = trained.json()
        version = training_body["registered_model_version"]

        async with session_factory() as session:
            user = await UserRepository(session).get_by_email(email)
            assert user is not None
            repository = TrainingJobRepository(session)
            job_id = uuid4()
            specification = RandomForestRegressionJobSpec(
                training_features=((0.0,), (1.0,), (2.0,), (3.0,)),
                training_targets=(0.0, 1.0, 2.0, 3.0),
                evaluation_features=((0.5,), (2.5,)),
                evaluation_targets=(0.5, 2.5),
                hyperparameters={"n_estimators": 3, "n_jobs": 1},
                experiment_name="AI API Regression",
                registered_model_name=training_body["registered_model_name"],
                tags={},
            )
            await repository.create(
                job_id=job_id,
                requested_by_user_id=user.id,
                key=random_forest_key(TaskType.REGRESSION),
                specification=specification,
                idempotency_key=None,
                request_fingerprint=specification.fingerprint(),
                max_attempts=3,
                queued_at=utc_now(),
            )
            claimed = await repository.claim_queued(
                job_id=job_id,
                started_at=utc_now(),
            )
            assert claimed is not None
            completed = await repository.mark_succeeded(
                job_id=job_id,
                expected_version=claimed.state_version,
                finished_at=utc_now(),
                local_execution_run_id=UUID(training_body["run_id"]),
                mlflow_experiment_id=training_body["mlflow_experiment_id"],
                mlflow_run_id=training_body["mlflow_run_id"],
                registered_model_version=version,
                metrics=training_body["metrics"],
            )
            assert completed is not None
            await repository.commit()

        model_name = training_body["registered_model_name"]
        challenger = await client.post(
            f"/ai/models/{model_name}/versions/{version}/promotions/challenger",
            headers=headers,
            json={},
        )
        champion = await client.post(
            f"/ai/models/{model_name}/versions/{version}/promotions/champion",
            headers=headers,
            json={},
        )
        aliases = await client.get(
            f"/ai/models/{model_name}/aliases",
            headers=headers,
        )
        audits = await client.get(
            f"/ai/models/{model_name}/promotions",
            headers=headers,
        )
        prediction = await client.post(
            "/ai/predictions/random-forest/regression",
            headers=headers,
            json={
                "registered_model_name": model_name,
                "version_or_alias": "champion",
                "features": [[0.75], [2.75]],
            },
        )

    assert challenger.status_code == 200
    assert champion.status_code == 200
    assert champion.json()["selected_version"] == version
    assert {item["alias"] for item in aliases.json()["aliases"]} == {
        "challenger",
        "champion",
    }
    assert audits.json()["total"] == 2
    assert prediction.status_code == 200
    assert prediction.json()["model_version"] == version


@pytest.mark.anyio
async def test_promotion_api_sanitizes_external_registry_failures(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Known external exceptions never expose SDK or infrastructure details."""
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, application):
        application.dependency_overrides[get_model_promotion_service] = (
            FailingPromotionService
        )
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="promotion-failure@example.com",
        )
        response = await client.post(
            "/ai/models/ai_core_random_forest_regression/versions/1/"
            "promotions/challenger",
            headers=headers,
            json={},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == ("An external model registry operation failed.")
    assert "credential" not in response.text


@pytest.mark.anyio
async def test_promotion_audit_finalization_failure_is_not_a_policy_conflict(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Post-alias audit persistence failure maps to sanitized HTTP 503, not 409."""
    async with ai_api_client(
        settings,
        session_factory,
        tmp_path=tmp_path,
    ) as (client, application):
        application.dependency_overrides[get_model_promotion_service] = (
            FailingPromotionFinalizationService
        )
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="promotion-finalization@example.com",
        )
        response = await client.post(
            "/ai/models/ai_core_random_forest_regression/versions/1/"
            "promotions/challenger",
            headers=headers,
            json={},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Promotion audit finalization requires operational reconciliation."
    )
    assert "database" not in response.text
