"""Dedicated worker orchestration for one persisted training-job UUID."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from uuid import UUID, uuid4

import numpy as np
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ml.artifacts import ArtifactManagerError
from app.ml.base import TrainerInput, TrainerKey
from app.ml.composition import (
    PLUGIN_REGISTRY,
    create_plugin_training_plan,
    create_random_forest_classification_plan,
    create_random_forest_regression_plan,
)
from app.ml.engine import TrainingModelTypeMismatchError
from app.ml.jobs.models import (
    PluginClassificationJobSpec,
    PluginRegressionJobSpec,
    RandomForestClassificationJobSpec,
    RandomForestRegressionJobSpec,
    TrainingJobRecord,
    TrainingJobSpec,
    TrainingJobStatus,
)
from app.ml.metrics import MetricsDataValidationError, MetricsReport
from app.ml.monitoring import (
    ModelReferenceProfileDraft,
    build_model_reference_profile_draft,
)
from app.ml.plugins import PluginTrainer
from app.ml.registry import (
    ModelRegistryError,
    ModelRegistryValidationError,
    RegisteredModelVersionNotFoundError,
    RegistryMetadataError,
)
from app.ml.services import (
    TrackedTrainingRequest,
    TrackedTrainingResult,
    TrackedTrainingService,
)
from app.ml.tracking import (
    ExperimentTrackingError,
    TrackingValidationError,
    normalize_tracking_parameters,
)
from app.ml.trainers.random_forest import (
    RandomForestClassifierTrainer,
    RandomForestRegressorTrainer,
    TrainerDataValidationError,
)
from app.ml.trainers.random_forest.types import (
    ClassificationPredictionArray,
    ClassificationTargetArray,
    FeatureArray,
    RegressionPredictionArray,
    RegressionTargetArray,
)
from app.models.user import AuditEvent
from app.observability.logging import emit_safe
from app.observability.metrics import record_training_job_finished
from app.repositories.ai_governance import TrainingJobRepository
from app.repositories.ai_monitoring import PredictionMonitoringRepository
from app.utils.security import utc_now

logger = logging.getLogger(__name__)


class WorkerExecutionState(StrEnum):
    """Internal result used by the actor to decide whether to raise for retry."""

    SUCCEEDED = "succeeded"
    RETRY = "retry"
    TERMINAL = "terminal"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class BackgroundTrainingOutcome:
    """External identifiers extracted from a successful typed execution."""

    local_execution_run_id: UUID
    mlflow_experiment_id: str
    mlflow_run_id: str
    registered_model_version: str
    metrics: Mapping[str, float]
    reference_profile: ModelReferenceProfileDraft | None = None


type TrainingSpecExecutor = Callable[[TrainingJobSpec], BackgroundTrainingOutcome]
type CandidateAliasAssigner = Callable[[str, str], None]


class TrainingJobWorker:
    """Claim once, execute synchronously, and persist a terminal or retry state."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        execute_specification: TrainingSpecExecutor,
        assign_candidate_alias: CandidateAliasAssigner,
    ) -> None:
        self._session_factory = session_factory
        self._execute_specification = execute_specification
        self._assign_candidate_alias = assign_candidate_alias

    async def execute(self, job_id: UUID) -> WorkerExecutionState:
        """Process one at-least-once delivery using persistent state as authority."""
        started_clock = perf_counter()
        async with self._session_factory() as session:
            repository = TrainingJobRepository(session)
            claimed = await repository.claim_queued(
                job_id=job_id,
                started_at=utc_now(),
            )
            if claimed is None:
                await repository.rollback()
                return WorkerExecutionState.SKIPPED
            await repository.commit()

        def finished(state: WorkerExecutionState) -> WorkerExecutionState:
            if state in {WorkerExecutionState.SUCCEEDED, WorkerExecutionState.TERMINAL}:
                final_status = (
                    "succeeded" if state is WorkerExecutionState.SUCCEEDED else "failed"
                )
                record_training_job_finished(
                    task_type=claimed.key.task_type.value,
                    algorithm=claimed.key.algorithm.value,
                    final_status=final_status,
                    duration_seconds=max(perf_counter() - started_clock, 0.0),
                )
                emit_safe(
                    logger,
                    logging.INFO,
                    "training_job_outcome",
                    extra={
                        "job_name": "training",
                        "task_type": claimed.key.task_type.value,
                        "algorithm": claimed.key.algorithm.value,
                        "lifecycle_status": final_status,
                        "attempt_number": claimed.attempt_count,
                        "duration_ms": round(
                            max(perf_counter() - started_clock, 0.0) * 1000,
                            3,
                        ),
                    },
                )
            return state

        expected_version = claimed.state_version
        try:
            outcome = _checkpointed_outcome(claimed)
            if outcome is None:
                outcome = self._execute_specification(claimed.specification)
                async with self._session_factory() as session:
                    repository = TrainingJobRepository(session)
                    checkpointed = await repository.record_external_result(
                        job_id=job_id,
                        expected_version=expected_version,
                        local_execution_run_id=outcome.local_execution_run_id,
                        mlflow_experiment_id=outcome.mlflow_experiment_id,
                        mlflow_run_id=outcome.mlflow_run_id,
                        registered_model_version=outcome.registered_model_version,
                        metrics=outcome.metrics,
                    )
                    if checkpointed is None:
                        await repository.rollback()
                        return WorkerExecutionState.SKIPPED
                    await repository.commit()
                    expected_version = checkpointed.state_version
            self._assign_candidate_alias(
                claimed.registered_model_name,
                outcome.registered_model_version,
            )
        except (
            ModelRegistryValidationError,
            RegistryMetadataError,
            TrackingValidationError,
            ArtifactManagerError,
            MetricsDataValidationError,
            TrainerDataValidationError,
            TrainingModelTypeMismatchError,
            ValidationError,
            ValueError,
        ):
            emit_safe(
                logger,
                logging.ERROR,
                "training_job_execution_failed",
                extra={
                    "job_name": "training",
                    "task_type": claimed.key.task_type.value,
                    "algorithm": claimed.key.algorithm.value,
                    "lifecycle_status": "validation_failed",
                    "attempt_number": claimed.attempt_count,
                },
                exc_info=True,
            )
            return finished(
                await self._fail(
                    job_id=job_id,
                    expected_version=expected_version,
                    error_code="training_validation_failed",
                    safe_error_message=(
                        "The persisted training request could not be executed."
                    ),
                )
            )
        except (
            ExperimentTrackingError,
            ModelRegistryError,
            RegisteredModelVersionNotFoundError,
            OSError,
        ):
            emit_safe(
                logger,
                logging.ERROR,
                "training_job_execution_failed",
                extra={
                    "job_name": "training",
                    "task_type": claimed.key.task_type.value,
                    "algorithm": claimed.key.algorithm.value,
                    "lifecycle_status": "retryable_failure",
                    "attempt_number": claimed.attempt_count,
                },
                exc_info=True,
            )
            if claimed.attempt_count < claimed.max_attempts:
                return await self._retry(
                    job_id=job_id,
                    expected_version=expected_version,
                    error_code="external_service_unavailable",
                    safe_error_message=(
                        "A temporary training integration failure occurred."
                    ),
                )
            return finished(
                await self._fail(
                    job_id=job_id,
                    expected_version=expected_version,
                    error_code="retry_exhausted",
                    safe_error_message=(
                        "Training failed after the configured retry limit."
                    ),
                )
            )
        except Exception:
            emit_safe(
                logger,
                logging.ERROR,
                "training_job_execution_failed",
                extra={
                    "job_name": "training",
                    "task_type": claimed.key.task_type.value,
                    "algorithm": claimed.key.algorithm.value,
                    "lifecycle_status": "unexpected_failure",
                    "attempt_number": claimed.attempt_count,
                },
                exc_info=True,
            )
            return finished(
                await self._fail(
                    job_id=job_id,
                    expected_version=expected_version,
                    error_code="training_execution_failed",
                    safe_error_message="The training job failed during execution.",
                )
            )

        await self._persist_reference_profile(
            job_id=job_id,
            draft=outcome.reference_profile,
        )

        async with self._session_factory() as session:
            repository = TrainingJobRepository(session)
            completed = await repository.mark_succeeded(
                job_id=job_id,
                expected_version=expected_version,
                finished_at=utc_now(),
                local_execution_run_id=outcome.local_execution_run_id,
                mlflow_experiment_id=outcome.mlflow_experiment_id,
                mlflow_run_id=outcome.mlflow_run_id,
                registered_model_version=outcome.registered_model_version,
                metrics=outcome.metrics,
            )
            if completed is None:
                await repository.rollback()
                emit_safe(
                    logger,
                    logging.WARNING,
                    "training_job_completion_conflict",
                    extra={
                        "job_name": "training",
                        "task_type": claimed.key.task_type.value,
                        "algorithm": claimed.key.algorithm.value,
                        "lifecycle_status": "skipped",
                        "attempt_number": claimed.attempt_count,
                    },
                )
                return WorkerExecutionState.SKIPPED
            session.add(
                AuditEvent(
                    company_id=completed.company_id,
                    actor_user_id=completed.requested_by_user_id,
                    actor_role=None,
                    action="training.succeeded",
                    resource_type="training_job",
                    resource_id=str(completed.id),
                    result="success",
                    safe_metadata={
                        "algorithm": completed.key.algorithm.value,
                        "task_type": completed.key.task_type.value,
                        "model_version": completed.registered_model_version,
                    },
                    retention_class="operations",
                )
            )
            await repository.commit()
        return finished(WorkerExecutionState.SUCCEEDED)

    async def _persist_reference_profile(
        self,
        *,
        job_id: UUID,
        draft: ModelReferenceProfileDraft | None,
    ) -> None:
        """Checkpoint a noncritical version profile without changing job success."""
        if draft is None:
            return
        async with self._session_factory() as session:
            repository = PredictionMonitoringRepository(session)
            try:
                await repository.create_reference_profile(
                    draft.finalize(profile_id=uuid4(), training_job_id=job_id),
                )
                await repository.commit()
            except Exception:
                emit_safe(
                    logger,
                    logging.ERROR,
                    "reference_profile_persistence_failed",
                    extra={
                        "job_name": "training",
                        "lifecycle_status": "checkpoint_failed",
                    },
                    exc_info=True,
                )
                try:
                    await repository.rollback()
                except Exception:
                    emit_safe(
                        logger,
                        logging.ERROR,
                        "reference_profile_rollback_failed",
                        extra={
                            "job_name": "training",
                            "lifecycle_status": "rollback_failed",
                        },
                        exc_info=True,
                    )

    async def _retry(
        self,
        *,
        job_id: UUID,
        expected_version: int,
        error_code: str,
        safe_error_message: str,
    ) -> WorkerExecutionState:
        async with self._session_factory() as session:
            repository = TrainingJobRepository(session)
            released = await repository.release_for_retry(
                job_id=job_id,
                expected_version=expected_version,
                error_code=error_code,
                safe_error_message=safe_error_message,
                queued_at=utc_now(),
            )
            if released is None:
                await repository.rollback()
                return WorkerExecutionState.SKIPPED
            await repository.commit()
        return WorkerExecutionState.RETRY

    async def _fail(
        self,
        *,
        job_id: UUID,
        expected_version: int,
        error_code: str,
        safe_error_message: str,
    ) -> WorkerExecutionState:
        async with self._session_factory() as session:
            repository = TrainingJobRepository(session)
            failed = await repository.mark_failed(
                job_id=job_id,
                expected_status=TrainingJobStatus.RUNNING,
                expected_version=expected_version,
                error_code=error_code,
                safe_error_message=safe_error_message,
                finished_at=utc_now(),
            )
            if failed is None:
                await repository.rollback()
                return WorkerExecutionState.SKIPPED
            session.add(
                AuditEvent(
                    company_id=failed.company_id,
                    actor_user_id=failed.requested_by_user_id,
                    actor_role=None,
                    action="training.failed",
                    resource_type="training_job",
                    resource_id=str(failed.id),
                    result="failure",
                    safe_metadata={
                        "algorithm": failed.key.algorithm.value,
                        "task_type": failed.key.task_type.value,
                        "error_code": error_code,
                    },
                    retention_class="operations",
                )
            )
            await repository.commit()
        return WorkerExecutionState.TERMINAL


def execute_tracked_training_specification(
    specification: TrainingJobSpec,
    *,
    service: TrackedTrainingService,
    profile_bin_count: int = 10,
) -> BackgroundTrainingOutcome:
    """Rebuild and execute one typed tracked-training task plan."""
    if isinstance(specification, RandomForestRegressionJobSpec):
        return _execute_regression(specification, service, profile_bin_count)
    if isinstance(specification, RandomForestClassificationJobSpec):
        return _execute_classification(specification, service, profile_bin_count)
    return _execute_plugin(specification, service, profile_bin_count)


def _execute_regression(
    specification: RandomForestRegressionJobSpec,
    service: TrackedTrainingService,
    profile_bin_count: int,
) -> BackgroundTrainingOutcome:
    training_features: FeatureArray = np.asarray(
        specification.training_features,
        dtype=np.float64,
    )
    training_targets: RegressionTargetArray = np.asarray(
        specification.training_targets,
        dtype=np.float64,
    )
    evaluation_features: FeatureArray = np.asarray(
        specification.evaluation_features,
        dtype=np.float64,
    )
    evaluation_targets: RegressionTargetArray = np.asarray(
        specification.evaluation_targets,
        dtype=np.float64,
    )
    parameters = specification.hyperparameters.model_dump()
    result = service.execute(
        TrackedTrainingRequest(
            plan=create_random_forest_regression_plan(
                training_input=TrainerInput(
                    features=training_features,
                    targets=training_targets,
                    hyperparameters=parameters,
                    random_seed=specification.random_seed,
                ),
                evaluation_features=evaluation_features,
                evaluation_targets=evaluation_targets,
            ),
            experiment_name=specification.experiment_name,
            run_name=specification.run_name,
            registered_model_name=specification.registered_model_name,
            tracking_parameters=normalize_tracking_parameters(
                {**parameters, "workflow_random_seed": specification.random_seed},
            ),
            tracking_tags=specification.tags,
            model_description=specification.model_description,
        ),
    )
    predictions = RandomForestRegressorTrainer().predict(
        result.execution.model,
        evaluation_features,
    )
    return _outcome(
        result,
        reference_profile=_safe_reference_profile(
            registered_model_name=specification.registered_model_name,
            model_version=result.registered_model.version,
            key=result.registered_model.key,
            evaluation_features=evaluation_features,
            predictions=predictions,
            profile_bin_count=profile_bin_count,
        ),
    )


def _execute_classification(
    specification: RandomForestClassificationJobSpec,
    service: TrackedTrainingService,
    profile_bin_count: int,
) -> BackgroundTrainingOutcome:
    training_features: FeatureArray = np.asarray(
        specification.training_features,
        dtype=np.float64,
    )
    training_targets: ClassificationTargetArray = np.asarray(
        specification.training_targets,
        dtype=np.int64,
    )
    evaluation_features: FeatureArray = np.asarray(
        specification.evaluation_features,
        dtype=np.float64,
    )
    evaluation_targets: ClassificationTargetArray = np.asarray(
        specification.evaluation_targets,
        dtype=np.int64,
    )
    parameters = specification.hyperparameters.model_dump()
    result = service.execute(
        TrackedTrainingRequest(
            plan=create_random_forest_classification_plan(
                training_input=TrainerInput(
                    features=training_features,
                    targets=training_targets,
                    hyperparameters=parameters,
                    random_seed=specification.random_seed,
                ),
                evaluation_features=evaluation_features,
                evaluation_targets=evaluation_targets,
            ),
            experiment_name=specification.experiment_name,
            run_name=specification.run_name,
            registered_model_name=specification.registered_model_name,
            tracking_parameters=normalize_tracking_parameters(
                {**parameters, "workflow_random_seed": specification.random_seed},
            ),
            tracking_tags=specification.tags,
            model_description=specification.model_description,
        ),
    )
    predictions = RandomForestClassifierTrainer().predict(
        result.execution.model,
        evaluation_features,
    )
    return _outcome(
        result,
        reference_profile=_safe_reference_profile(
            registered_model_name=specification.registered_model_name,
            model_version=result.registered_model.version,
            key=result.registered_model.key,
            evaluation_features=evaluation_features,
            predictions=predictions,
            profile_bin_count=profile_bin_count,
        ),
    )


def _execute_plugin(
    specification: PluginRegressionJobSpec | PluginClassificationJobSpec,
    service: TrackedTrainingService,
    profile_bin_count: int,
) -> BackgroundTrainingOutcome:
    """Execute any allowlisted non-Random-Forest plugin through the shared engine."""
    plugin = PLUGIN_REGISTRY.get(specification.plugin_id)
    training_features: FeatureArray = np.asarray(
        specification.training_features,
        dtype=np.float64,
    )
    evaluation_features: FeatureArray = np.asarray(
        specification.evaluation_features,
        dtype=np.float64,
    )
    if isinstance(specification, PluginClassificationJobSpec):
        training_targets = np.asarray(specification.training_targets, dtype=np.int64)
        evaluation_targets = np.asarray(
            specification.evaluation_targets, dtype=np.int64
        )
    else:
        training_targets = np.asarray(specification.training_targets, dtype=np.float64)
        evaluation_targets = np.asarray(
            specification.evaluation_targets, dtype=np.float64
        )
    parameters = dict(specification.hyperparameters)
    training_parameters = {
        **parameters,
        "__scaler": specification.preprocessing.scaler,
        "__imputer": specification.preprocessing.imputer,
    }
    result = service.execute(
        TrackedTrainingRequest(
            plan=create_plugin_training_plan(
                key=plugin.key,
                training_input=TrainerInput(
                    features=training_features,
                    targets=training_targets,
                    hyperparameters=training_parameters,
                    random_seed=specification.random_seed,
                ),
                evaluation_features=evaluation_features,
                evaluation_targets=evaluation_targets,
            ),
            experiment_name=specification.experiment_name,
            run_name=specification.run_name,
            registered_model_name=specification.registered_model_name,
            tracking_parameters=normalize_tracking_parameters(
                {
                    **parameters,
                    "preprocessing.scaler": specification.preprocessing.scaler,
                    "preprocessing.imputer": specification.preprocessing.imputer,
                    "workflow_random_seed": specification.random_seed,
                    "feature_count": training_features.shape[1],
                    "training_rows": training_features.shape[0],
                    "evaluation_rows": evaluation_features.shape[0],
                }
            ),
            tracking_tags=specification.tags,
            model_description=specification.model_description,
        )
    )
    predictions = PluginTrainer(plugin).predict(
        result.execution.model,
        evaluation_features,
    )
    return _outcome(
        result,
        reference_profile=_safe_reference_profile(
            registered_model_name=specification.registered_model_name,
            model_version=result.registered_model.version,
            key=result.registered_model.key,
            evaluation_features=evaluation_features,
            predictions=predictions,
            profile_bin_count=profile_bin_count,
        ),
    )


def _outcome[
    ModelT, ReportT: MetricsReport
](
    result: TrackedTrainingResult[ModelT, ReportT],
    *,
    reference_profile: ModelReferenceProfileDraft | None,
) -> BackgroundTrainingOutcome:
    return BackgroundTrainingOutcome(
        local_execution_run_id=result.execution.run_id,
        mlflow_experiment_id=result.tracking.experiment_id,
        mlflow_run_id=result.tracking.run_id,
        registered_model_version=result.registered_model.version,
        metrics=result.execution.metrics_report.to_mapping(),
        reference_profile=reference_profile,
    )


def _safe_reference_profile(
    *,
    registered_model_name: str,
    model_version: str,
    key: TrainerKey,
    evaluation_features: FeatureArray,
    predictions: RegressionPredictionArray | ClassificationPredictionArray,
    profile_bin_count: int,
) -> ModelReferenceProfileDraft | None:
    """Treat profile construction as recoverable monitoring degradation."""
    try:
        return build_model_reference_profile_draft(
            registered_model_name=registered_model_name,
            model_version=model_version,
            key=key,
            evaluation_features=evaluation_features,
            predictions=predictions,
            bin_count=profile_bin_count,
            created_at=utc_now(),
        )
    except Exception:
        emit_safe(
            logger,
            logging.ERROR,
            "reference_profile_construction_failed",
            extra={
                "job_name": "training",
                "task_type": key.task_type.value,
                "algorithm": key.algorithm.value,
                "lifecycle_status": "profile_degraded",
            },
            exc_info=True,
        )
        return None


def _checkpointed_outcome(job: TrainingJobRecord) -> BackgroundTrainingOutcome | None:
    if (
        job.local_execution_run_id is None
        or job.mlflow_experiment_id is None
        or job.mlflow_run_id is None
        or job.registered_model_version is None
        or job.metrics is None
    ):
        return None
    return BackgroundTrainingOutcome(
        local_execution_run_id=job.local_execution_run_id,
        mlflow_experiment_id=job.mlflow_experiment_id,
        mlflow_run_id=job.mlflow_run_id,
        registered_model_version=job.registered_model_version,
        metrics=job.metrics,
        reference_profile=None,
    )
