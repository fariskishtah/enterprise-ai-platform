"""Isolated real-service background training and candidate prediction smoke test."""

from pathlib import Path
from uuid import UUID

import numpy as np
import pytest
from app.config.settings import Settings
from app.ml.composition import (
    create_ai_model_registry,
    create_ai_tracked_training_service,
    create_random_forest_regression_prediction_plan,
)
from app.ml.domain import TaskType
from app.ml.jobs import RandomForestRegressionJobSpec, random_forest_key
from app.ml.jobs.service import TrainingJobService
from app.ml.jobs.worker import (
    TrainingJobWorker,
    WorkerExecutionState,
    execute_tracked_training_specification,
)
from app.ml.services import (
    MLflowRegisteredModelLoader,
    PredictionService,
    RegisteredPredictionRequest,
)
from app.ml.trainers.random_forest.types import FeatureArray
from app.models.user import User, UserRole
from app.repositories.ai_governance import TrainingJobRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SmokeQueue:
    """Record the UUID that a real worker invocation consumes in-process."""

    def __init__(self) -> None:
        self.job_id: UUID | None = None

    def enqueue(self, training_job_id: UUID) -> str:
        self.job_id = training_job_id
        return f"smoke-{training_job_id}"


@pytest.mark.anyio
async def test_real_background_training_candidate_and_prediction_smoke(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Persist, consume, train, track, register candidate, and predict locally."""
    user = User(
        email="background-smoke@example.com",
        hashed_password="not-used",
        role=UserRole.ENGINEER,
        is_active=True,
    )
    async with session_factory() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)

    resolved_settings = settings.model_copy(
        update={
            "mlflow_tracking_uri": f"file:{tmp_path / 'mlruns'}",
            "ai_artifact_root": str(tmp_path / "ai-artifacts"),
        },
    )
    specification = RandomForestRegressionJobSpec(
        training_features=((0.0,), (1.0,), (2.0,), (3.0,)),
        training_targets=(0.0, 1.0, 2.0, 3.0),
        evaluation_features=((0.5,), (2.5,)),
        evaluation_targets=(0.5, 2.5),
        hyperparameters={"n_estimators": 3, "n_jobs": 1},
        random_seed=17,
        experiment_name="Background Smoke",
        registered_model_name="ai_core_random_forest_regression",
        tags={"purpose": "background-smoke"},
    )
    queue = SmokeQueue()
    async with session_factory() as session:
        submission = await TrainingJobService(
            repository=TrainingJobRepository(session),
            queue=queue,
            max_attempts=3,
        ).submit(
            requested_by_user_id=user.id,
            key=random_forest_key(TaskType.REGRESSION),
            specification=specification,
            idempotency_key="background-smoke",
        )

    registry = create_ai_model_registry(resolved_settings)
    tracked_service = create_ai_tracked_training_service(
        resolved_settings,
        model_registry=registry,
    )

    def assign_candidate_alias(model_name: str, version: str) -> None:
        registry.assign_alias(model_name, "candidate", version)

    worker = TrainingJobWorker(
        session_factory=session_factory,
        execute_specification=lambda persisted: (
            execute_tracked_training_specification(
                persisted,
                service=tracked_service,
            )
        ),
        assign_candidate_alias=assign_candidate_alias,
    )
    assert queue.job_id == submission.job.id
    worker_result = await worker.execute(submission.job.id)

    async with session_factory() as session:
        completed = await TrainingJobRepository(session).get_by_id(submission.job.id)

    assert worker_result is WorkerExecutionState.SUCCEEDED
    assert completed is not None
    assert completed.status.value == "succeeded"
    assert completed.registered_model_version == "1"
    assert (
        registry.resolve(
            completed.registered_model_name,
            "candidate",
        ).version
        == "1"
    )

    features: FeatureArray = np.asarray([[0.75], [2.75]], dtype=np.float64)
    prediction = PredictionService(
        model_registry=registry,
        model_loader=MLflowRegisteredModelLoader(
            tracking_uri=resolved_settings.mlflow_tracking_uri,
        ),
    ).predict(
        create_random_forest_regression_prediction_plan(),
        RegisteredPredictionRequest(
            registered_model_name=completed.registered_model_name,
            version_or_alias="candidate",
            features=features,
        ),
    )
    assert prediction.model_version.version == "1"
    assert prediction.predictions.shape == (2,)
