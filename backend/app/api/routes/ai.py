"""Synchronous tracked-training and registered-prediction routes."""

from typing import Annotated

import numpy as np
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, status
from pydantic import ValidationError

from app.config.settings import Settings, get_settings
from app.dependencies.auth import require_roles
from app.dependencies.rate_limit import enforce_mutation_rate_limit
from app.dependencies.services import (
    get_ai_model_registry,
    get_ai_monitored_prediction_service,
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
from app.ml.monitoring import MonitoredPredictionService, PredictionCaptureContext
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

_AUTH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "description": "A valid bearer access token is required.",
    },
    status.HTTP_403_FORBIDDEN: {
        "description": "The authenticated account is inactive or lacks permission.",
    },
}
_TRAINING_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **_AUTH_ERROR_RESPONSES,
    status.HTTP_409_CONFLICT: {
        "description": (
            "The local artifact or fitted model conflicts with the expected "
            "training contract."
        ),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "description": "Request or AI platform validation failed.",
    },
    status.HTTP_502_BAD_GATEWAY: {
        "description": (
            "MLflow tracking or model registration failed. The response detail is "
            "sanitized."
        ),
    },
}
_PREDICTION_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **_AUTH_ERROR_RESPONSES,
    status.HTTP_404_NOT_FOUND: {
        "description": "The requested registered model version or alias was not found.",
    },
    status.HTTP_409_CONFLICT: {
        "description": (
            "Resolved metadata or the fitted model does not match the requested "
            "trainer contract."
        ),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "description": "Request or AI platform validation failed.",
    },
    status.HTTP_502_BAD_GATEWAY: {
        "description": (
            "The external model registry or artifact download failed. The response "
            "detail is sanitized."
        ),
    },
}
_MODEL_LOOKUP_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **_AUTH_ERROR_RESPONSES,
    status.HTTP_404_NOT_FOUND: {
        "description": "The requested registered model version or alias was not found.",
    },
    status.HTTP_409_CONFLICT: {
        "description": "The resolved model version lacks valid AI Core metadata.",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "description": "The model name, version, or alias is invalid.",
    },
    status.HTTP_502_BAD_GATEWAY: {
        "description": (
            "The external model registry lookup failed. The response detail is "
            "sanitized."
        ),
    },
}

_REGRESSION_TRAINING_EXAMPLE: dict[str, object] = {
    "training_features": [
        [0.0, 1.0],
        [1.0, 1.5],
        [2.0, 2.0],
        [3.0, 2.5],
    ],
    "training_targets": [1.0, 2.0, 3.0, 4.0],
    "evaluation_features": [[0.5, 1.25], [2.5, 2.25]],
    "evaluation_targets": [1.5, 3.5],
    "hyperparameters": {"n_estimators": 5, "n_jobs": 1},
    "random_seed": 17,
    "experiment_name": "AI Core Manual Demo",
    "run_name": "regression-demo",
    "registered_model_name": "ai_core_random_forest_regression",
    "tags": {"purpose": "manual-demo"},
}
_CLASSIFICATION_TRAINING_EXAMPLE: dict[str, object] = {
    "training_features": [
        [0.0, 0.5],
        [0.5, 1.0],
        [2.5, 2.0],
        [3.0, 2.5],
    ],
    "training_targets": [0, 0, 1, 1],
    "evaluation_features": [[0.25, 0.75], [2.75, 2.25]],
    "evaluation_targets": [0, 1],
    "hyperparameters": {"n_estimators": 5, "n_jobs": 1},
    "random_seed": 19,
    "experiment_name": "AI Core Manual Demo",
    "run_name": "classification-demo",
    "registered_model_name": "ai_core_random_forest_classification",
    "tags": {"purpose": "manual-demo"},
}
_REGRESSION_PREDICTION_EXAMPLE: dict[str, object] = {
    "registered_model_name": "ai_core_random_forest_regression",
    "version_or_alias": "1",
    "features": [[0.75, 1.4], [2.75, 2.4]],
}
_CLASSIFICATION_PREDICTION_EXAMPLE: dict[str, object] = {
    "registered_model_name": "ai_core_random_forest_classification",
    "version_or_alias": "1",
    "features": [[0.25, 0.75], [2.75, 2.25]],
}

_REGRESSION_TRAINING_DESCRIPTION = """
Train a Random Forest regressor from a finite numeric feature matrix and target
vector. **Admin or engineer role required.** The request is handled synchronously:
transport validation is followed by explicit float64 NumPy conversion, fitting,
held-out regression metrics, local Joblib persistence, a FINISHED MLflow run, and
registration of a new immutable model version.

Training and evaluation matrices must be non-empty, rectangular, and have equal
column counts; each target vector must contain one finite numeric value per row.
This endpoint supports only the platform's intentionally restricted Random Forest
contract. It does not enqueue work, promote aliases, roll back completed external
steps, or expose local artifact-manager paths.
"""
_CLASSIFICATION_TRAINING_DESCRIPTION = """
Train a Random Forest classifier for strict integer labels. **Admin or engineer
role required.** The request runs synchronously through transport validation,
float64 feature and int64 target conversion, fitting, held-out classification
metrics, local Joblib persistence, a FINISHED MLflow run, and registration of a
new immutable model version.

Feature matrices must be non-empty, rectangular, and width-compatible; target
vectors must contain one integer label per row and training data must represent at
least two classes. The endpoint does not accept non-integer labels, enqueue work,
predict probabilities, promote aliases, or perform cross-system rollback.
"""
_REGRESSION_PREDICTION_DESCRIPTION = """
Resolve an existing Random Forest regression model by exact positive version or
pre-existing alias and return one float prediction per feature row. **Admin,
engineer, or operator role required.** Prediction is synchronous. Finite numeric
rows are converted to a rectangular float64 matrix, and the protected TrainerKey
is checked before the Joblib artifact is downloaded or deserialized.

The endpoint does not retrain, register, promote, or return probability output.
Missing versions return 404; trainer/model conflicts return 409; external registry
or artifact failures return a sanitized 502.
"""
_CLASSIFICATION_PREDICTION_DESCRIPTION = """
Resolve an existing Random Forest integer-label classifier by exact positive
version or pre-existing alias and return one integer label per feature row.
**Admin, engineer, or operator role required.** Prediction is synchronous. Finite
numeric rows are converted to a rectangular float64 matrix, and the protected
TrainerKey is checked before the Joblib artifact is downloaded or deserialized.

The endpoint does not retrain, register, promote, or return class probabilities.
Missing versions return 404; trainer/model conflicts return 409; external registry
or artifact failures return a sanitized 502.
"""
_MODEL_LOOKUP_DESCRIPTION = """
Resolve immutable registry metadata for an exact positive version or a pre-existing
alias without loading the fitted model. **Admin, engineer, or operator role
required.** The synchronous read returns the exact resolved version, source MLflow
run, protected trainer identity, registration status, and current aliases. It does
not assign aliases, promote models, download artifacts, or change registry state.
"""


@router.post(
    "/training/random-forest/regression",
    response_model=AITrainingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Train and register a Random Forest regressor",
    description=_REGRESSION_TRAINING_DESCRIPTION,
    response_description=(
        "Completed execution UUID, trainer identity, held-out metrics, MLflow "
        "experiment/run/artifact identifiers, registered model name and version, "
        "and fitting duration."
    ),
    responses=_TRAINING_ERROR_RESPONSES,
)
def train_random_forest_regression(
    payload: Annotated[
        RandomForestRegressionTrainingRequest,
        Body(
            openapi_examples={
                "small_regression": {
                    "summary": "Small deterministic regression training request",
                    "value": _REGRESSION_TRAINING_EXAMPLE,
                },
            },
        ),
    ],
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
    description=_CLASSIFICATION_TRAINING_DESCRIPTION,
    response_description=(
        "Completed execution UUID, classification trainer identity, held-out "
        "metrics, MLflow experiment/run/artifact identifiers, registered model "
        "name and version, and fitting duration."
    ),
    responses=_TRAINING_ERROR_RESPONSES,
)
def train_random_forest_classification(
    payload: Annotated[
        RandomForestClassificationTrainingRequest,
        Body(
            openapi_examples={
                "small_classification": {
                    "summary": (
                        "Small deterministic integer-label classification request"
                    ),
                    "value": _CLASSIFICATION_TRAINING_EXAMPLE,
                },
            },
        ),
    ],
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
    dependencies=[Depends(enforce_mutation_rate_limit)],
    response_model=RegressionPredictionResponse,
    status_code=status.HTTP_200_OK,
    summary="Predict with a registered Random Forest regressor",
    description=_REGRESSION_PREDICTION_DESCRIPTION,
    response_description=(
        "Resolved model name and exact version, validated trainer identity, and "
        "one float prediction per input row."
    ),
    responses=_PREDICTION_ERROR_RESPONSES,
)
async def predict_random_forest_regression(
    payload: Annotated[
        RegisteredModelPredictionRequest,
        Body(
            openapi_examples={
                "exact_version": {
                    "summary": "Regression prediction by exact model version",
                    "value": _REGRESSION_PREDICTION_EXAMPLE,
                },
            },
        ),
    ],
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[
        MonitoredPredictionService,
        Depends(get_ai_monitored_prediction_service),
    ],
    correlation_id: Annotated[
        str | None,
        Header(alias="X-Correlation-ID", min_length=1, max_length=128),
    ] = None,
) -> RegressionPredictionResponse:
    """Return float predictions from an exact registered model reference."""
    features: FeatureArray = np.asarray(payload.features, dtype=np.float64)
    try:
        result = await service.predict(
            create_random_forest_regression_prediction_plan(),
            RegisteredPredictionRequest(
                registered_model_name=payload.registered_model_name,
                version_or_alias=payload.version_or_alias,
                features=features,
            ),
            PredictionCaptureContext(
                requested_by_user_id=current_user.id,
                correlation_id=correlation_id,
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
    dependencies=[Depends(enforce_mutation_rate_limit)],
    response_model=ClassificationPredictionResponse,
    status_code=status.HTTP_200_OK,
    summary="Predict with a registered Random Forest classifier",
    description=_CLASSIFICATION_PREDICTION_DESCRIPTION,
    response_description=(
        "Resolved model name and exact version, validated trainer identity, and "
        "one integer class label per input row."
    ),
    responses=_PREDICTION_ERROR_RESPONSES,
)
async def predict_random_forest_classification(
    payload: Annotated[
        RegisteredModelPredictionRequest,
        Body(
            openapi_examples={
                "exact_version": {
                    "summary": "Classification prediction by exact model version",
                    "value": _CLASSIFICATION_PREDICTION_EXAMPLE,
                },
            },
        ),
    ],
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[
        MonitoredPredictionService,
        Depends(get_ai_monitored_prediction_service),
    ],
    correlation_id: Annotated[
        str | None,
        Header(alias="X-Correlation-ID", min_length=1, max_length=128),
    ] = None,
) -> ClassificationPredictionResponse:
    """Return integer labels from an exact registered model reference."""
    features: FeatureArray = np.asarray(payload.features, dtype=np.float64)
    try:
        result = await service.predict(
            create_random_forest_classification_prediction_plan(),
            RegisteredPredictionRequest(
                registered_model_name=payload.registered_model_name,
                version_or_alias=payload.version_or_alias,
                features=features,
            ),
            PredictionCaptureContext(
                requested_by_user_id=current_user.id,
                correlation_id=correlation_id,
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
    description=_MODEL_LOOKUP_DESCRIPTION,
    response_description=(
        "Resolved registered model name and exact version, source MLflow run, "
        "protected trainer identity, registration status, and current aliases."
    ),
    responses=_MODEL_LOOKUP_ERROR_RESPONSES,
)
def get_registered_model_version(
    registered_model_name: Annotated[
        str,
        Path(
            description="Safe lower-case registered-model name.",
            examples=["ai_core_random_forest_regression"],
        ),
    ],
    version_or_alias: Annotated[
        str,
        Path(
            description="Exact positive model version or an existing registry alias.",
            examples=["1"],
        ),
    ],
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
