"""Authenticated persistent background-training routes."""

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Response,
    status,
)

from app.config.settings import Settings, get_settings
from app.dependencies.auth import require_roles
from app.dependencies.services import get_training_job_service
from app.ml.domain import TaskType
from app.ml.jobs import (
    RandomForestClassificationJobSpec,
    RandomForestRegressionJobSpec,
    TrainingJobConflictError,
    TrainingJobEnqueueError,
    TrainingJobNotFoundError,
    TrainingJobQueuePersistenceError,
    TrainingJobRecord,
    TrainingJobSpec,
    TrainingJobStatus,
    TrainingJobSubmission,
    random_forest_key,
)
from app.ml.jobs.service import TrainingJobService
from app.ml.registry import build_registered_model_name
from app.models.user import User, UserRole
from app.schemas.ai import (
    RandomForestClassificationTrainingRequest,
    RandomForestRegressionTrainingRequest,
    TrainerKeyResponse,
)
from app.schemas.ai_governance import (
    TrainingJobPageResponse,
    TrainingJobResponse,
    TrainingJobSubmissionResponse,
)

router = APIRouter(prefix="/ai", tags=["ai"])

_AUTH_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"description": "A valid bearer access token is required."},
    403: {"description": "The authenticated role is not permitted."},
}
_JOB_SUBMISSION_RESPONSES: dict[int | str, dict[str, object]] = {
    **_AUTH_RESPONSES,
    409: {"description": "The idempotency key conflicts with another payload."},
    503: {
        "description": (
            "The queue is unavailable or an enqueued job requires operational "
            "reconciliation."
        ),
    },
}
_JOB_READ_RESPONSES: dict[int | str, dict[str, object]] = {
    **_AUTH_RESPONSES,
    404: {"description": "The job does not exist in the authorized scope."},
}


@router.post(
    "/training-jobs/random-forest/regression",
    response_model=TrainingJobSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit Random Forest regression training",
    description=(
        "Persist a validated regression specification and enqueue only its UUID. "
        "Admin or engineer role required. Optional Idempotency-Key retries are "
        "scoped to the requesting user and task."
    ),
    responses=_JOB_SUBMISSION_RESPONSES,
)
async def submit_random_forest_regression_job(
    payload: RandomForestRegressionTrainingRequest,
    response: Response,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[TrainingJobService, Depends(get_training_job_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", max_length=128),
    ] = None,
) -> TrainingJobSubmissionResponse:
    """Persist and enqueue a JSON-validated regression job."""
    registered_model_name = (
        payload.registered_model_name
        or build_registered_model_name(
            random_forest_key(TaskType.REGRESSION),
            prefix=settings.ai_default_registered_model_prefix,
        )
    )
    specification = RandomForestRegressionJobSpec(
        training_features=tuple(tuple(row) for row in payload.training_features),
        training_targets=tuple(payload.training_targets),
        evaluation_features=tuple(tuple(row) for row in payload.evaluation_features),
        evaluation_targets=tuple(payload.evaluation_targets),
        hyperparameters=payload.hyperparameters.model_dump(),
        random_seed=payload.random_seed,
        experiment_name=payload.experiment_name,
        run_name=payload.run_name,
        registered_model_name=registered_model_name,
        tags=payload.tags,
        model_description=payload.model_description,
    )
    submission = await _submit(
        service=service,
        current_user=current_user,
        specification=specification,
        idempotency_key=idempotency_key,
    )
    if not submission.created:
        response.status_code = status.HTTP_200_OK
    return _submission_response(submission.job)


@router.post(
    "/training-jobs/random-forest/classification",
    response_model=TrainingJobSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit Random Forest classification training",
    description=(
        "Persist a validated integer-label classification specification and "
        "enqueue only its UUID. Admin or engineer role required."
    ),
    responses=_JOB_SUBMISSION_RESPONSES,
)
async def submit_random_forest_classification_job(
    payload: RandomForestClassificationTrainingRequest,
    response: Response,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[TrainingJobService, Depends(get_training_job_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", max_length=128),
    ] = None,
) -> TrainingJobSubmissionResponse:
    """Persist and enqueue a JSON-validated classification job."""
    registered_model_name = (
        payload.registered_model_name
        or build_registered_model_name(
            random_forest_key(TaskType.CLASSIFICATION),
            prefix=settings.ai_default_registered_model_prefix,
        )
    )
    specification = RandomForestClassificationJobSpec(
        training_features=tuple(tuple(row) for row in payload.training_features),
        training_targets=tuple(payload.training_targets),
        evaluation_features=tuple(tuple(row) for row in payload.evaluation_features),
        evaluation_targets=tuple(payload.evaluation_targets),
        hyperparameters=payload.hyperparameters.model_dump(),
        random_seed=payload.random_seed,
        experiment_name=payload.experiment_name,
        run_name=payload.run_name,
        registered_model_name=registered_model_name,
        tags=payload.tags,
        model_description=payload.model_description,
    )
    submission = await _submit(
        service=service,
        current_user=current_user,
        specification=specification,
        idempotency_key=idempotency_key,
    )
    if not submission.created:
        response.status_code = status.HTTP_200_OK
    return _submission_response(submission.job)


@router.get(
    "/training-jobs/{job_id}",
    response_model=TrainingJobResponse,
    summary="Get a background training job",
    description=(
        "Return safe lifecycle, attempt, metrics, and external identifier fields. "
        "Admins see all jobs; engineers may retrieve only their own."
    ),
    responses=_JOB_READ_RESPONSES,
)
async def get_training_job(
    job_id: UUID,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[TrainingJobService, Depends(get_training_job_service)],
) -> TrainingJobResponse:
    """Return one admin-visible or engineer-owned job."""
    try:
        job = await service.get_authorized(
            job_id=job_id,
            current_user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
        )
    except TrainingJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _job_response(job)


@router.get(
    "/training-jobs",
    response_model=TrainingJobPageResponse,
    summary="List background training jobs",
    responses=_AUTH_RESPONSES,
)
async def list_training_jobs(
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[TrainingJobService, Depends(get_training_job_service)],
    job_status: Annotated[
        TrainingJobStatus | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TrainingJobPageResponse:
    """Return newest jobs within the caller's authorized scope."""
    page = await service.list_authorized(
        current_user_id=current_user.id,
        is_admin=current_user.role is UserRole.ADMIN,
        status=job_status,
        limit=limit,
        offset=offset,
    )
    return TrainingJobPageResponse(
        items=[_job_response(job) for job in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/training-jobs/{job_id}/cancel",
    response_model=TrainingJobResponse,
    summary="Cancel a queued training job",
    description=(
        "Cancel only a queued job. Running sklearn fits do not support cooperative "
        "cancellation and return a conflict."
    ),
    responses={**_JOB_READ_RESPONSES, 409: {"description": "The job is not queued."}},
)
async def cancel_training_job(
    job_id: UUID,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[TrainingJobService, Depends(get_training_job_service)],
) -> TrainingJobResponse:
    """Persist cancellation only before a worker claims the job."""
    try:
        return _job_response(
            await service.cancel(
                job_id=job_id,
                current_user_id=current_user.id,
                is_admin=current_user.role is UserRole.ADMIN,
            ),
        )
    except TrainingJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TrainingJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _submit(
    *,
    service: TrainingJobService,
    current_user: User,
    specification: TrainingJobSpec,
    idempotency_key: str | None,
) -> TrainingJobSubmission:
    try:
        return await service.submit(
            requested_by_user_id=current_user.id,
            key=random_forest_key(
                (
                    TaskType.REGRESSION
                    if isinstance(specification, RandomForestRegressionJobSpec)
                    else TaskType.CLASSIFICATION
                ),
            ),
            specification=specification,
            idempotency_key=idempotency_key,
        )
    except TrainingJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except TrainingJobEnqueueError as exc:
        raise HTTPException(
            status_code=503,
            detail="The training worker queue is unavailable.",
        ) from exc
    except TrainingJobQueuePersistenceError as exc:
        raise HTTPException(
            status_code=503,
            detail="The queued job requires operational reconciliation.",
        ) from exc


def _submission_response(job: TrainingJobRecord) -> TrainingJobSubmissionResponse:
    return TrainingJobSubmissionResponse(
        job_id=job.id,
        status=job.status,
        submitted_at=job.created_at,
        status_url=f"/ai/training-jobs/{job.id}",
    )


def _job_response(job: TrainingJobRecord) -> TrainingJobResponse:
    return TrainingJobResponse(
        job_id=job.id,
        requested_by_user_id=job.requested_by_user_id,
        trainer_key=TrainerKeyResponse(
            algorithm=job.key.algorithm,
            task_type=job.key.task_type,
        ),
        status=job.status,
        created_at=job.created_at,
        queued_at=job.queued_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        cancelled_at=job.cancelled_at,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        metrics=dict(job.metrics) if job.metrics is not None else None,
        local_execution_run_id=job.local_execution_run_id,
        mlflow_experiment_id=job.mlflow_experiment_id,
        mlflow_run_id=job.mlflow_run_id,
        registered_model_name=job.registered_model_name,
        registered_model_version=job.registered_model_version,
        error_code=job.error_code,
        safe_error_message=job.safe_error_message,
    )
