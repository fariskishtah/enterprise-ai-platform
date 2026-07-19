"""Opt-in real Redis/Dramatiq background-training integration smoke test."""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import numpy as np
import pytest
from app import models as app_models
from app.config.settings import get_settings
from app.db.base import Base
from app.db.session import build_engine, build_session_factory
from app.ml.composition import create_random_forest_regression_prediction_plan
from app.ml.domain import TaskType
from app.ml.jobs import (
    DramatiqTrainingJobQueue,
    RandomForestRegressionJobSpec,
    TrainingJobRecord,
    TrainingJobStatus,
    random_forest_key,
)
from app.ml.jobs.service import TrainingJobService
from app.ml.registry import MLflowModelRegistry
from app.ml.services import (
    MLflowRegisteredModelLoader,
    PredictionService,
    RegisteredPredictionRequest,
)
from app.ml.trainers.random_forest.types import FeatureArray
from app.models.user import User, UserRole
from app.repositories.ai_governance import TrainingJobRepository
from redis import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_ = app_models
RUN_REDIS_INTEGRATION = os.getenv("RUN_AI_REDIS_INTEGRATION") == "1"


@pytest.mark.integration
@pytest.mark.skipif(
    not RUN_REDIS_INTEGRATION,
    reason="Set RUN_AI_REDIS_INTEGRATION=1 with a disposable local Redis DB.",
)
def test_real_redis_worker_training_candidate_and_prediction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Consume a UUID through real Redis and a dedicated Dramatiq subprocess."""
    redis_url = os.getenv(
        "AI_TEST_REDIS_URL",
        "redis://localhost:6379/15",
    )
    parsed_redis = urlparse(redis_url)
    if parsed_redis.hostname not in {"localhost", "127.0.0.1"}:
        pytest.fail("The opt-in smoke test requires a loopback Redis host.")
    if parsed_redis.path != "/15":
        pytest.fail("The opt-in smoke test requires disposable Redis database 15.")

    redis_client: Redis = Redis.from_url(redis_url)
    redis_client.ping()
    redis_client.flushdb()

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'worker.db'}"
    tracking_uri = f"file:{tmp_path / 'mlruns'}"
    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "REDIS_URL": redis_url,
        "SECRET_KEY": "integration-test-secret-with-sufficient-entropy",
        "ENVIRONMENT": "test",
        "MLFLOW_TRACKING_URI": tracking_uri,
        "AI_ARTIFACT_ROOT": str(tmp_path / "ai-artifacts"),
        "MODEL_ARTIFACT_ROOT": str(tmp_path / "model-artifacts"),
        "TRAINING_JOB_RETRY_BASE_SECONDS": "0.1",
    }
    get_settings.cache_clear()
    for key in (
        "DATABASE_URL",
        "REDIS_URL",
        "SECRET_KEY",
        "ENVIRONMENT",
        "MLFLOW_TRACKING_URI",
        "AI_ARTIFACT_ROOT",
        "MODEL_ARTIFACT_ROOT",
        "TRAINING_JOB_RETRY_BASE_SECONDS",
    ):
        monkeypatch.setenv(key, environment[key])

    session_factory = asyncio.run(_prepare_database(database_url))
    job_id = asyncio.run(_submit_job(session_factory))
    worker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "dramatiq",
            "app.ml.jobs.tasks",
            "--processes",
            "1",
            "--threads",
            "1",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        completed = _poll_job(session_factory, job_id, timeout_seconds=30)
        assert completed.status is TrainingJobStatus.SUCCEEDED
        assert completed.registered_model_version == "1"
        registry = MLflowModelRegistry(tracking_uri=tracking_uri)
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
            model_loader=MLflowRegisteredModelLoader(tracking_uri=tracking_uri),
        ).predict(
            create_random_forest_regression_prediction_plan(),
            RegisteredPredictionRequest(
                completed.registered_model_name,
                "candidate",
                features,
            ),
        )
        assert prediction.predictions.shape == (2,)
    finally:
        worker.terminate()
        worker.wait(timeout=10)
        redis_client.flushdb()
        redis_client.close()
        get_settings.cache_clear()


async def _prepare_database(
    database_url: str,
) -> async_sessionmaker[AsyncSession]:
    engine = build_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    return build_session_factory(database_url)


async def _submit_job(
    session_factory: async_sessionmaker[AsyncSession],
) -> UUID:
    user = User(
        email="redis-integration@example.com",
        hashed_password="not-used",
        role=UserRole.ENGINEER,
        is_active=True,
    )
    async with session_factory() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)
        specification = RandomForestRegressionJobSpec(
            training_features=((0.0,), (1.0,), (2.0,), (3.0,)),
            training_targets=(0.0, 1.0, 2.0, 3.0),
            evaluation_features=((0.5,), (2.5,)),
            evaluation_targets=(0.5, 2.5),
            hyperparameters={"n_estimators": 3, "n_jobs": 1},
            random_seed=17,
            experiment_name="Redis Background Smoke",
            registered_model_name="ai_core_random_forest_regression",
            tags={"purpose": "redis-integration"},
        )
        submission = await TrainingJobService(
            repository=TrainingJobRepository(session),
            queue=DramatiqTrainingJobQueue(),
            max_attempts=3,
        ).submit(
            requested_by_user_id=user.id,
            key=random_forest_key(TaskType.REGRESSION),
            specification=specification,
            idempotency_key="redis-smoke",
        )
    return submission.job.id


def _poll_job(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
    *,
    timeout_seconds: float,
) -> TrainingJobRecord:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        job = asyncio.run(_get_job(session_factory, job_id))
        assert job is not None
        if job.status in {
            TrainingJobStatus.SUCCEEDED,
            TrainingJobStatus.FAILED,
        }:
            return job
        time.sleep(0.2)
    raise AssertionError("The real Redis background job did not finish in time.")


async def _get_job(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: UUID,
) -> TrainingJobRecord | None:
    async with session_factory() as session:
        return await TrainingJobRepository(session).get_by_id(job_id)
