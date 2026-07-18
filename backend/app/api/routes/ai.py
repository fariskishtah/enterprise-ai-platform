"""Synchronous tracked-training and registered-prediction routes."""

from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from app.config.settings import Settings, get_settings
from app.dependencies.auth import require_roles
from app.dependencies.services import (
    get_ai_model_registry,
    get_ai_prediction_service,
    get_ai_tracked_training_service,
)
from app.ml.artifacts import ArtifactAlreadyExistsError
from app.ml.base import TrainerInput, TrainerKey
from app.ml.composition import (
    create_random_forest_classification_plan,
    create_random_forest_classification_prediction_plan,
    create_random_forest_regression_plan,
    create_random_forest_regression_prediction_plan,
)
from app.ml.engine import TrainingModelTypeMismatchError
from app.ml.metrics import MetricsDataValidationError, MetricsReport
from app.ml.registry import (
    BaseModelRegistry,
    ModelRegistryError,
    ModelRegistryValidationError,
    RegisteredModelVersion,
    RegisteredModelVersionNotFoundError,
    RegistryMetadataError,
    build_registered_model_name,
)
from app.ml.services import (
    PredictionService,
    PredictionTrainerKeyMismatchError,
    RegisteredModelLoadError,
    RegisteredModelTypeMismatchError,
    RegisteredPredictionRequest,
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
    RANDOM_FOREST_CLASSIFIER_REGISTRATION,
    RANDOM_FOREST_REGRESSOR_REGISTRATION,
    TrainerDataValidationError,
)
from app.ml.trainers.random_forest.types import (
    ClassificationTargetArray,
    FeatureArray,
    RegressionTargetArray,
)
from app.models.user import User, UserRole
from app.schemas.ai import (
    AITrainingResponse,
    ClassificationPredictionResponse,
    RandomForestClassificationTrainingRequest,
    RandomForestRegressionTrainingRequest,
    RegisteredModelPredictionRequest,
    RegisteredModelVersionResponse,
    RegressionPredictionResponse,
    TrainerKeyResponse,
)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post(
    "/training/random-forest/regression",
    response_model=AITrainingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Train and register a Random Forest regressor",
)
def train_random_forest_regression(
    payload: RandomForestRegressionTrainingRequest,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[
        TrackedTrainingService,
        Depends(get_ai_tracked_training_service),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AITrainingResponse:
    """Execute synchronous regression training, tracking, and registration."""
    training_features: FeatureArray = np.asarray(
        payload.training_features,
        dtype=np.float64,
    )
    training_targets: RegressionTargetArray = np.asarray(
        payload.training_targets,
        dtype=np.float64,
    )
    evaluation_features: FeatureArray = np.asarray(
        payload.evaluation_features,
        dtype=np.float64,
    )
    evaluation_targets: RegressionTargetArray = np.asarray(
        payload.evaluation_targets,
        dtype=np.float64,
    )
    parameters = payload.hyperparameters.model_dump()
    try:
        registered_model_name = (
            payload.registered_model_name
            or build_registered_model_name(
                RANDOM_FOREST_REGRESSOR_REGISTRATION.key,
                prefix=settings.ai_default_registered_model_prefix,
            )
        )
        request = TrackedTrainingRequest(
            plan=create_random_forest_regression_plan(
                training_input=TrainerInput(
                    features=training_features,
                    targets=training_targets,
                    hyperparameters=parameters,
                    random_seed=payload.random_seed,
                ),
                evaluation_features=evaluation_features,
                evaluation_targets=evaluation_targets,
            ),
            experiment_name=payload.experiment_name,
            run_name=payload.run_name,
            registered_model_name=registered_model_name,
            tracking_parameters=_tracking_parameters(parameters, payload.random_seed),
            tracking_tags=payload.tags,
            model_description=payload.model_description,
        )
        return _training_response(service.execute(request))
    except (
        MetricsDataValidationError,
        ModelRegistryValidationError,
        TrackingValidationError,
        TrainerDataValidationError,
        ValidationError,
    ) as exc:
        raise _unprocessable(exc) from exc
    except (ArtifactAlreadyExistsError, TrainingModelTypeMismatchError) as exc:
        raise _conflict(exc) from exc
    except (ExperimentTrackingError, ModelRegistryError) as exc:
        raise _bad_gateway() from exc


@router.post(
    "/training/random-forest/classification",
    response_model=AITrainingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Train and register a Random Forest classifier",
)
def train_random_forest_classification(
    payload: RandomForestClassificationTrainingRequest,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[
        TrackedTrainingService,
        Depends(get_ai_tracked_training_service),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AITrainingResponse:
    """Execute synchronous classification training and registration."""
    training_features: FeatureArray = np.asarray(
        payload.training_features,
        dtype=np.float64,
    )
    training_targets: ClassificationTargetArray = np.asarray(
        payload.training_targets,
        dtype=np.int64,
    )
    evaluation_features: FeatureArray = np.asarray(
        payload.evaluation_features,
        dtype=np.float64,
    )
    evaluation_targets: ClassificationTargetArray = np.asarray(
        payload.evaluation_targets,
        dtype=np.int64,
    )
    parameters = payload.hyperparameters.model_dump()
    try:
        registered_model_name = (
            payload.registered_model_name
            or build_registered_model_name(
                RANDOM_FOREST_CLASSIFIER_REGISTRATION.key,
                prefix=settings.ai_default_registered_model_prefix,
            )
        )
        request = TrackedTrainingRequest(
            plan=create_random_forest_classification_plan(
                training_input=TrainerInput(
                    features=training_features,
                    targets=training_targets,
                    hyperparameters=parameters,
                    random_seed=payload.random_seed,
                ),
                evaluation_features=evaluation_features,
                evaluation_targets=evaluation_targets,
            ),
            experiment_name=payload.experiment_name,
            run_name=payload.run_name,
            registered_model_name=registered_model_name,
            tracking_parameters=_tracking_parameters(parameters, payload.random_seed),
            tracking_tags=payload.tags,
            model_description=payload.model_description,
        )
        return _training_response(service.execute(request))
    except (
        MetricsDataValidationError,
        ModelRegistryValidationError,
        TrackingValidationError,
        TrainerDataValidationError,
        ValidationError,
    ) as exc:
        raise _unprocessable(exc) from exc
    except (ArtifactAlreadyExistsError, TrainingModelTypeMismatchError) as exc:
        raise _conflict(exc) from exc
    except (ExperimentTrackingError, ModelRegistryError) as exc:
        raise _bad_gateway() from exc


@router.post(
    "/predictions/random-forest/regression",
    response_model=RegressionPredictionResponse,
    status_code=status.HTTP_200_OK,
    summary="Predict with a registered Random Forest regressor",
)
def predict_random_forest_regression(
    payload: RegisteredModelPredictionRequest,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[PredictionService, Depends(get_ai_prediction_service)],
) -> RegressionPredictionResponse:
    """Return float predictions from an exact registered model reference."""
    features: FeatureArray = np.asarray(payload.features, dtype=np.float64)
    try:
        result = service.predict(
            create_random_forest_regression_prediction_plan(),
            RegisteredPredictionRequest(
                registered_model_name=payload.registered_model_name,
                version_or_alias=payload.version_or_alias,
                features=features,
            ),
        )
    except (ModelRegistryValidationError, TrainerDataValidationError) as exc:
        raise _unprocessable(exc) from exc
    except RegisteredModelVersionNotFoundError as exc:
        raise _not_found(exc) from exc
    except (
        PredictionTrainerKeyMismatchError,
        RegisteredModelTypeMismatchError,
        RegistryMetadataError,
    ) as exc:
        raise _conflict(exc) from exc
    except (ModelRegistryError, RegisteredModelLoadError) as exc:
        raise _bad_gateway() from exc
    return RegressionPredictionResponse(
        model_name=result.model_version.registered_model_name,
        model_version=result.model_version.version,
        trainer_key=_trainer_key_response(result.model_version.key),
        predictions=[float(value) for value in result.predictions],
    )


@router.post(
    "/predictions/random-forest/classification",
    response_model=ClassificationPredictionResponse,
    status_code=status.HTTP_200_OK,
    summary="Predict with a registered Random Forest classifier",
)
def predict_random_forest_classification(
    payload: RegisteredModelPredictionRequest,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[PredictionService, Depends(get_ai_prediction_service)],
) -> ClassificationPredictionResponse:
    """Return integer labels from an exact registered model reference."""
    features: FeatureArray = np.asarray(payload.features, dtype=np.float64)
    try:
        result = service.predict(
            create_random_forest_classification_prediction_plan(),
            RegisteredPredictionRequest(
                registered_model_name=payload.registered_model_name,
                version_or_alias=payload.version_or_alias,
                features=features,
            ),
        )
    except (ModelRegistryValidationError, TrainerDataValidationError) as exc:
        raise _unprocessable(exc) from exc
    except RegisteredModelVersionNotFoundError as exc:
        raise _not_found(exc) from exc
    except (
        PredictionTrainerKeyMismatchError,
        RegisteredModelTypeMismatchError,
        RegistryMetadataError,
    ) as exc:
        raise _conflict(exc) from exc
    except (ModelRegistryError, RegisteredModelLoadError) as exc:
        raise _bad_gateway() from exc
    return ClassificationPredictionResponse(
        model_name=result.model_version.registered_model_name,
        model_version=result.model_version.version,
        trainer_key=_trainer_key_response(result.model_version.key),
        predictions=[int(value) for value in result.predictions],
    )


@router.get(
    "/models/{registered_model_name}/versions/{version_or_alias}",
    response_model=RegisteredModelVersionResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve a registered AI model version",
)
def get_registered_model_version(
    registered_model_name: str,
    version_or_alias: str,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    registry: Annotated[BaseModelRegistry, Depends(get_ai_model_registry)],
) -> RegisteredModelVersionResponse:
    """Resolve an exact version or alias without changing registry state."""
    try:
        return _model_version_response(
            registry.resolve(registered_model_name, version_or_alias),
        )
    except ModelRegistryValidationError as exc:
        raise _unprocessable(exc) from exc
    except RegisteredModelVersionNotFoundError as exc:
        raise _not_found(exc) from exc
    except RegistryMetadataError as exc:
        raise _conflict(exc) from exc
    except ModelRegistryError as exc:
        raise _bad_gateway() from exc


def _tracking_parameters(
    parameters: dict[str, object],
    random_seed: int | None,
) -> dict[str, str | int | float | bool | None]:
    supplied = {**parameters, "workflow_random_seed": random_seed}
    return dict(normalize_tracking_parameters(supplied))


def _training_response[
    ModelT, ReportT: MetricsReport
](result: TrackedTrainingResult[ModelT, ReportT],) -> AITrainingResponse:
    return AITrainingResponse(
        run_id=result.execution.run_id,
        trainer_key=_trainer_key_response(result.execution.key),
        metrics=dict(result.execution.metrics_report.to_mapping()),
        mlflow_experiment_id=result.tracking.experiment_id,
        mlflow_run_id=result.tracking.run_id,
        mlflow_artifact_uri=result.tracking.artifact_uri,
        registered_model_name=result.registered_model.registered_model_name,
        registered_model_version=result.registered_model.version,
        duration_seconds=result.execution.training_duration_seconds,
    )


def _model_version_response(
    model_version: RegisteredModelVersion,
) -> RegisteredModelVersionResponse:
    return RegisteredModelVersionResponse(
        model_name=model_version.registered_model_name,
        model_version=model_version.version,
        run_id=model_version.run_id,
        trainer_key=_trainer_key_response(model_version.key),
        status=model_version.status,
        aliases=model_version.aliases,
    )


def _trainer_key_response(key: TrainerKey) -> TrainerKeyResponse:
    return TrainerKeyResponse(
        algorithm=key.algorithm,
        task_type=key.task_type,
    )


def _unprocessable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _bad_gateway() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="An external model service operation failed.",
    )
