"""MLOps experiment management routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies.auth import require_roles
from app.dependencies.services import get_mlops_service
from app.models.mlops import TrainingRunStatus
from app.models.user import User, UserRole
from app.schemas.common import PaginatedResponse, SortOrder
from app.schemas.mlops import (
    ExperimentCreate,
    ExperimentResponse,
    ExperimentSortField,
    ModelArtifactCreate,
    ModelArtifactResponse,
    ModelArtifactSortField,
    TrainingRunCreate,
    TrainingRunResponse,
    TrainingRunSortField,
)
from app.services.exceptions import (
    DuplicateExperimentNameError,
    DuplicateModelArtifactVersionError,
    InvalidTrainingRunError,
    RelatedResourceNotFoundError,
    ResourceNotFoundError,
)
from app.services.mlops import MLOpsService

experiments_router = APIRouter(prefix="/experiments", tags=["experiments"])
experiment_training_runs_router = APIRouter(
    prefix="/experiments",
    tags=["training-runs"],
)
training_runs_router = APIRouter(prefix="/training-runs", tags=["training-runs"])
training_run_artifacts_router = APIRouter(
    prefix="/training-runs",
    tags=["model-artifacts"],
)
model_artifacts_router = APIRouter(
    prefix="/model-artifacts",
    tags=["model-artifacts"],
)


def _not_found(exc: ResourceNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _related_not_found(exc: RelatedResourceNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


def _experiment_conflict(exc: DuplicateExperimentNameError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _artifact_conflict(exc: DuplicateModelArtifactVersionError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _invalid_training_run(exc: InvalidTrainingRunError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


@experiments_router.post(
    "",
    response_model=ExperimentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an experiment",
)
async def create_experiment(
    payload: ExperimentCreate,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[MLOpsService, Depends(get_mlops_service)],
) -> ExperimentResponse:
    """Create an experiment."""
    try:
        experiment = await service.create_experiment(
            name=payload.name,
            description=payload.description,
            created_by=current_user.id,
        )
    except DuplicateExperimentNameError as exc:
        raise _experiment_conflict(exc) from exc
    return ExperimentResponse.model_validate(experiment)


@experiments_router.get(
    "",
    response_model=PaginatedResponse[ExperimentResponse],
    status_code=status.HTTP_200_OK,
    summary="List experiments",
)
async def list_experiments(
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[MLOpsService, Depends(get_mlops_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    created_by: UUID | None = None,
    sort_by: ExperimentSortField = ExperimentSortField.CREATED_AT,
    sort_order: SortOrder = SortOrder.DESC,
) -> PaginatedResponse[ExperimentResponse]:
    """List experiments with pagination, filtering, search, and sorting."""
    page = await service.list_experiments(
        limit=limit,
        offset=offset,
        search=search,
        created_by=created_by,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse(
        items=[ExperimentResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@experiments_router.get(
    "/{experiment_id}",
    response_model=ExperimentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get an experiment",
)
async def get_experiment(
    experiment_id: UUID,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[MLOpsService, Depends(get_mlops_service)],
) -> ExperimentResponse:
    """Return an experiment by ID."""
    try:
        experiment = await service.get_experiment(experiment_id)
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    return ExperimentResponse.model_validate(experiment)


@experiment_training_runs_router.post(
    "/{experiment_id}/training-runs",
    response_model=TrainingRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a training run",
)
async def create_training_run(
    experiment_id: UUID,
    payload: TrainingRunCreate,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[MLOpsService, Depends(get_mlops_service)],
) -> TrainingRunResponse:
    """Create training-run metadata without training a model."""
    try:
        training_run = await service.create_training_run(
            experiment_id=experiment_id,
            dataset_version=payload.dataset_version,
            algorithm=payload.algorithm,
            parameters=payload.parameters,
            metrics=payload.metrics,
            status=payload.status,
            started_at=payload.started_at,
            finished_at=payload.finished_at,
        )
    except RelatedResourceNotFoundError as exc:
        raise _related_not_found(exc) from exc
    except InvalidTrainingRunError as exc:
        raise _invalid_training_run(exc) from exc
    return TrainingRunResponse.model_validate(training_run)


@training_runs_router.get(
    "",
    response_model=PaginatedResponse[TrainingRunResponse],
    status_code=status.HTTP_200_OK,
    summary="List training runs",
)
async def list_training_runs(
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[MLOpsService, Depends(get_mlops_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    experiment_id: UUID | None = None,
    dataset_version: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    algorithm: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    status_filter: Annotated[TrainingRunStatus | None, Query(alias="status")] = None,
    sort_by: TrainingRunSortField = TrainingRunSortField.STARTED_AT,
    sort_order: SortOrder = SortOrder.DESC,
) -> PaginatedResponse[TrainingRunResponse]:
    """List training runs with pagination and filtering."""
    page = await service.list_training_runs(
        limit=limit,
        offset=offset,
        experiment_id=experiment_id,
        dataset_version=dataset_version,
        algorithm=algorithm,
        status=status_filter,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse(
        items=[TrainingRunResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@training_runs_router.get(
    "/{training_run_id}",
    response_model=TrainingRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a training run",
)
async def get_training_run(
    training_run_id: UUID,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[MLOpsService, Depends(get_mlops_service)],
) -> TrainingRunResponse:
    """Return a training run by ID."""
    try:
        training_run = await service.get_training_run(training_run_id)
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    return TrainingRunResponse.model_validate(training_run)


@training_run_artifacts_router.post(
    "/{training_run_id}/model-artifacts",
    response_model=ModelArtifactResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a model artifact",
)
async def create_model_artifact(
    training_run_id: UUID,
    payload: ModelArtifactCreate,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[MLOpsService, Depends(get_mlops_service)],
) -> ModelArtifactResponse:
    """Register model artifact metadata."""
    try:
        model_artifact = await service.create_model_artifact(
            training_run_id=training_run_id,
            framework=payload.framework,
            model_type=payload.model_type,
            version=payload.version,
            artifact_path=payload.artifact_path,
            checksum=payload.checksum,
        )
    except RelatedResourceNotFoundError as exc:
        raise _related_not_found(exc) from exc
    except DuplicateModelArtifactVersionError as exc:
        raise _artifact_conflict(exc) from exc
    return ModelArtifactResponse.model_validate(model_artifact)


@model_artifacts_router.get(
    "",
    response_model=PaginatedResponse[ModelArtifactResponse],
    status_code=status.HTTP_200_OK,
    summary="List model artifacts",
)
async def list_model_artifacts(
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[MLOpsService, Depends(get_mlops_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    training_run_id: UUID | None = None,
    framework: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    model_type: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    version: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    sort_by: ModelArtifactSortField = ModelArtifactSortField.VERSION,
    sort_order: SortOrder = SortOrder.DESC,
) -> PaginatedResponse[ModelArtifactResponse]:
    """List model artifacts with pagination and filtering."""
    page = await service.list_model_artifacts(
        limit=limit,
        offset=offset,
        training_run_id=training_run_id,
        framework=framework,
        model_type=model_type,
        version=version,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse(
        items=[ModelArtifactResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@model_artifacts_router.get(
    "/{model_artifact_id}",
    response_model=ModelArtifactResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a model artifact",
)
async def get_model_artifact(
    model_artifact_id: UUID,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[MLOpsService, Depends(get_mlops_service)],
) -> ModelArtifactResponse:
    """Return a model artifact by ID."""
    try:
        model_artifact = await service.get_model_artifact(model_artifact_id)
    except ResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    return ModelArtifactResponse.model_validate(model_artifact)
