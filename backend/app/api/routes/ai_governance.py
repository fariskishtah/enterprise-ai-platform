"""Authenticated background-training and controlled-promotion routes."""

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Response,
    status,
)

from app.config.settings import Settings, get_settings
from app.dependencies.auth import require_roles
from app.dependencies.services import (
    get_model_promotion_service,
    get_training_job_service,
)
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
from app.ml.promotion import (
    ModelAlias,
    ModelPromotionRequest,
    ModelPromotionResult,
    PromotionAliasVerificationError,
    PromotionAuditFinalizationError,
    PromotionAuthorizationError,
    PromotionPolicyRejectedError,
    PromotionPreconditionError,
    PromotionValidationError,
)
from app.ml.promotion.service import ModelPromotionService
from app.ml.registry import (
    ModelRegistryError,
    ModelRegistryValidationError,
    RegisteredModelVersionNotFoundError,
    build_registered_model_name,
)
from app.models.user import User, UserRole
from app.repositories.ai_governance import PromotionAuditPage
from app.schemas.ai import (
    RandomForestClassificationTrainingRequest,
    RandomForestRegressionTrainingRequest,
    TrainerKeyResponse,
)
from app.schemas.ai_governance import (
    ModelAliasesResponse,
    ModelAliasResponse,
    ModelPromotionBody,
    ModelPromotionResponse,
    PromotionAuditPageResponse,
    PromotionAuditResponse,
    PromotionEvaluationResponse,
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
_PROMOTION_RESPONSES: dict[int | str, dict[str, object]] = {
    **_AUTH_RESPONSES,
    404: {"description": "The exact registered model version does not exist."},
    409: {"description": "Promotion policy or lifecycle preconditions rejected."},
    502: {"description": "The external registry failure detail is sanitized."},
    503: {"description": "Promotion audit persistence requires reconciliation."},
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


@router.post(
    "/models/{registered_model_name}/versions/{version}/promotions/challenger",
    response_model=ModelPromotionResponse,
    summary="Promote a model version to challenger",
    description=(
        "Evaluate task metrics and explicitly assign challenger. Admin or engineer "
        "role required; only admins may force a rejected evaluation with a reason."
    ),
    responses=_PROMOTION_RESPONSES,
)
async def promote_challenger(
    registered_model_name: Annotated[str, Path()],
    version: Annotated[str, Path()],
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[
        ModelPromotionService,
        Depends(get_model_promotion_service),
    ],
    payload: Annotated[ModelPromotionBody, Body()],
) -> ModelPromotionResponse:
    """Assign challenger after task policy evaluation."""
    return await _promote(
        registered_model_name=registered_model_name,
        version=version,
        target_alias=ModelAlias.CHALLENGER,
        payload=payload,
        current_user=current_user,
        service=service,
    )


@router.post(
    "/models/{registered_model_name}/versions/{version}/promotions/champion",
    response_model=ModelPromotionResponse,
    summary="Promote a challenger model version to champion",
    description=(
        "Admin-only explicit champion assignment after policy evaluation and "
        "challenger-transition validation. Training never calls this operation."
    ),
    responses=_PROMOTION_RESPONSES,
)
async def promote_champion(
    registered_model_name: Annotated[str, Path()],
    version: Annotated[str, Path()],
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN)),
    ],
    service: Annotated[
        ModelPromotionService,
        Depends(get_model_promotion_service),
    ],
    payload: Annotated[ModelPromotionBody, Body()],
) -> ModelPromotionResponse:
    """Assign champion only through an explicit admin request."""
    return await _promote(
        registered_model_name=registered_model_name,
        version=version,
        target_alias=ModelAlias.CHAMPION,
        payload=payload,
        current_user=current_user,
        service=service,
    )


@router.get(
    "/models/{registered_model_name}/promotions",
    response_model=PromotionAuditPageResponse,
    summary="List model promotion history",
    responses=_AUTH_RESPONSES,
)
async def list_model_promotions(
    registered_model_name: str,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[
        ModelPromotionService,
        Depends(get_model_promotion_service),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PromotionAuditPageResponse:
    """Return immutable audit history without exposing SDK responses."""
    try:
        page = await service.list_audits(
            registered_model_name=registered_model_name,
            limit=limit,
            offset=offset,
        )
    except ModelRegistryValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _audit_page_response(page, limit=limit, offset=offset)


@router.get(
    "/models/{registered_model_name}/aliases",
    response_model=ModelAliasesResponse,
    summary="List governed model aliases",
    responses={
        **_AUTH_RESPONSES,
        404: {"description": "The registered model does not exist."},
        502: {"description": "The external registry failure detail is sanitized."},
    },
)
def list_model_aliases(
    registered_model_name: str,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[
        ModelPromotionService,
        Depends(get_model_promotion_service),
    ],
) -> ModelAliasesResponse:
    """Return candidate, challenger, and champion holders when present."""
    try:
        aliases = service.list_aliases(registered_model_name)
    except ModelRegistryValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RegisteredModelVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ModelRegistryError as exc:
        raise HTTPException(
            status_code=502,
            detail="An external model registry operation failed.",
        ) from exc
    return ModelAliasesResponse(
        registered_model_name=registered_model_name,
        aliases=[
            ModelAliasResponse(alias=alias.alias, version=alias.version)
            for alias in aliases
        ],
    )


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


async def _promote(
    *,
    registered_model_name: str,
    version: str,
    target_alias: ModelAlias,
    payload: ModelPromotionBody,
    current_user: User,
    service: ModelPromotionService,
) -> ModelPromotionResponse:
    try:
        result = await service.promote(
            ModelPromotionRequest(
                registered_model_name=registered_model_name,
                version=version,
                target_alias=target_alias,
                requested_by_user_id=current_user.id,
                force=payload.force,
                reason=payload.reason,
            ),
            requester_role=current_user.role,
        )
    except RegisteredModelVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PromotionAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (PromotionPolicyRejectedError, PromotionPreconditionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (PromotionValidationError, ModelRegistryValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ModelRegistryError, PromotionAliasVerificationError) as exc:
        raise HTTPException(
            status_code=502,
            detail="An external model registry operation failed.",
        ) from exc
    except PromotionAuditFinalizationError as exc:
        raise HTTPException(
            status_code=503,
            detail="Promotion audit finalization requires operational reconciliation.",
        ) from exc
    return _promotion_response(result)


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


def _promotion_response(result: ModelPromotionResult) -> ModelPromotionResponse:
    evaluation = result.evaluation
    return ModelPromotionResponse(
        audit_id=result.audit_id,
        registered_model_name=result.registered_model_name,
        selected_version=result.selected_version,
        target_alias=result.target_alias,
        previous_version=result.previous_version,
        policy_evaluation=PromotionEvaluationResponse(
            accepted=evaluation.accepted,
            reason=evaluation.reason,
            primary_metric=evaluation.primary_metric,
            candidate_value=evaluation.candidate_value,
            incumbent_value=evaluation.incumbent_value,
            improvement=evaluation.improvement,
            safeguards=dict(evaluation.safeguards),
        ),
        overridden=result.overridden,
        completed_at=result.completed_at,
    )


def _audit_page_response(
    page: PromotionAuditPage,
    *,
    limit: int,
    offset: int,
) -> PromotionAuditPageResponse:
    return PromotionAuditPageResponse(
        items=[
            PromotionAuditResponse(
                audit_id=audit.id,
                registered_model_name=audit.registered_model_name,
                model_version=audit.model_version,
                trainer_key=TrainerKeyResponse(
                    algorithm=audit.key.algorithm,
                    task_type=audit.key.task_type,
                ),
                target_alias=audit.target_alias,
                previous_version=audit.previous_version,
                requested_by_user_id=audit.requested_by_user_id,
                action=audit.action,
                decision=audit.decision,
                policy_result=dict(audit.policy_result),
                force=audit.force,
                reason=audit.reason,
                operation_outcome=audit.operation_outcome,
                created_at=audit.created_at,
                completed_at=audit.completed_at,
                error_code=audit.error_code,
                safe_error_message=audit.safe_error_message,
            )
            for audit in page.items
        ],
        total=page.total,
        limit=limit,
        offset=offset,
    )
