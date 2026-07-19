"""Bounded reconciliation for missing model-version reference profiles."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from uuid import uuid4

import numpy as np

from app.config.settings import Settings, get_settings
from app.db.session import build_session_factory
from app.ml.composition import (
    create_ai_model_registry,
    create_random_forest_classification_prediction_plan,
    create_random_forest_regression_prediction_plan,
)
from app.ml.jobs import (
    RandomForestClassificationJobSpec,
    RandomForestRegressionJobSpec,
)
from app.ml.monitoring.models import ModelReferenceProfile
from app.ml.monitoring.profiles import build_model_reference_profile
from app.ml.services import (
    MLflowRegisteredModelLoader,
    PredictionService,
    RegisteredPredictionRequest,
)
from app.ml.trainers.random_forest.types import (
    ClassificationPredictionArray,
    FeatureArray,
    RegressionPredictionArray,
)
from app.repositories.ai_monitoring import (
    MissingReferenceProfileJob,
    PredictionMonitoringRepository,
)
from app.utils.security import utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReferenceReconciliationResult:
    """Bounded reconciliation counts safe for command output."""

    examined: int
    created: int
    failed: int


async def reconcile_missing_reference_profiles(
    settings: Settings,
) -> ReferenceReconciliationResult:
    """Build missing profiles without fitting or registering another model."""
    session_factory = build_session_factory(settings.database_url)
    registry = create_ai_model_registry(settings)
    prediction_service = PredictionService(
        model_registry=registry,
        model_loader=MLflowRegisteredModelLoader(
            tracking_uri=settings.mlflow_tracking_uri,
        ),
    )
    async with session_factory() as session:
        repository = PredictionMonitoringRepository(session)
        candidates = await repository.list_missing_reference_profiles(
            limit=settings.monitoring_reference_reconciliation_batch_size,
        )
        return await reconcile_reference_profile_candidates(
            repository=repository,
            candidates=candidates,
            prediction_service=prediction_service,
            bin_count=settings.monitoring_profile_bin_count,
        )


async def reconcile_reference_profile_candidates(
    *,
    repository: PredictionMonitoringRepository,
    candidates: tuple[MissingReferenceProfileJob, ...],
    prediction_service: PredictionService,
    bin_count: int,
) -> ReferenceReconciliationResult:
    """Attempt one bounded candidate set and isolate each operational failure."""
    created = 0
    failed = 0
    for candidate in candidates:
        try:
            profile = rebuild_reference_profile(
                candidate,
                prediction_service=prediction_service,
                bin_count=bin_count,
            )
            await repository.create_reference_profile(profile)
            await repository.commit()
            created += 1
        except Exception:
            failed += 1
            logger.exception(
                "Reference profile reconciliation failed for job %s; no "
                "training or registration was repeated.",
                candidate.id,
            )
            await repository.rollback()
    return ReferenceReconciliationResult(
        examined=len(candidates),
        created=created,
        failed=failed,
    )


def rebuild_reference_profile(
    candidate: MissingReferenceProfileJob,
    *,
    prediction_service: PredictionService,
    bin_count: int,
) -> ModelReferenceProfile:
    specification = candidate.specification
    features: FeatureArray = np.asarray(
        specification.evaluation_features,
        dtype=np.float64,
    )
    request = RegisteredPredictionRequest(
        registered_model_name=candidate.registered_model_name,
        version_or_alias=candidate.registered_model_version,
        features=features,
    )
    predictions: RegressionPredictionArray | ClassificationPredictionArray
    if isinstance(specification, RandomForestRegressionJobSpec):
        regression_result = prediction_service.predict(
            create_random_forest_regression_prediction_plan(),
            request,
        )
        predictions = regression_result.predictions
        resolved_key = regression_result.model_version.key
    elif isinstance(specification, RandomForestClassificationJobSpec):
        classification_result = prediction_service.predict(
            create_random_forest_classification_prediction_plan(),
            request,
        )
        predictions = classification_result.predictions
        resolved_key = classification_result.model_version.key
    else:
        raise ValueError("Unsupported persisted training specification.")
    if resolved_key.task_type is not candidate.key.task_type:
        raise ValueError("Resolved model task does not match the training job.")
    return build_model_reference_profile(
        profile_id=uuid4(),
        training_job_id=candidate.id,
        registered_model_name=candidate.registered_model_name,
        model_version=candidate.registered_model_version,
        key=candidate.key,
        evaluation_features=features,
        predictions=predictions,
        bin_count=bin_count,
        created_at=utc_now(),
    )


def main() -> None:
    """Run one configured reconciliation batch."""
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(reconcile_missing_reference_profiles(get_settings()))
    print(
        f"examined={result.examined} created={result.created} failed={result.failed}",
    )


if __name__ == "__main__":
    main()
