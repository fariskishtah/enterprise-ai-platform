"""Authenticated background-training and controlled-promotion routes."""

from typing import Annotated
from uuid import UUID

import numpy as np
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
from pydantic import ValidationError

from app.config.settings import Settings, get_settings
from app.datasets.service import (
    DatasetConflictError,
    DatasetNotFoundError,
    DatasetQueueError,
    DatasetService,
)
from app.dependencies.auth import require_roles
from app.dependencies.datasets import get_dataset_service
from app.dependencies.operational import require_training_worker_available
from app.dependencies.rate_limit import enforce_mutation_rate_limit
from app.dependencies.services import (
    get_ai_model_registry,
    get_ai_registered_model_loader,
    get_audit_service,
    get_model_promotion_service,
    get_training_job_service,
)
from app.ml.composition import PLUGIN_REGISTRY
from app.ml.domain import AlgorithmType, TaskType
from app.ml.evaluation import build_evaluation_payload
from app.ml.jobs import (
    PluginClassificationJobSpec,
    PluginRegressionJobSpec,
    PreprocessingJobConfig,
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
from app.ml.plugins import ModelPluginError
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
    BaseModelRegistry,
    ModelRegistryError,
    ModelRegistryValidationError,
    RegisteredModelVersionNotFoundError,
    build_registered_model_name,
)
from app.ml.services import BaseRegisteredModelLoader, RegisteredModelLoadError
from app.models.user import User, UserRole
from app.repositories.ai_governance import PromotionAuditPage
from app.schemas.ai import (
    RandomForestClassificationTrainingRequest,
    RandomForestRegressionTrainingRequest,
    TrainerKeyResponse,
)
from app.schemas.ai_governance import (
    AlgorithmResponse,
    GenericTrainingJobRequest,
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
from app.services.audit import AuditService

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


@router.get(
    "/algorithms",
    response_model=list[AlgorithmResponse],
    summary="Discover allowlisted training algorithms",
    responses=_AUTH_RESPONSES,
)
def list_algorithms(
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
) -> list[AlgorithmResponse]:
    """Return stable capability metadata without estimator internals."""
    return [
        AlgorithmResponse.model_validate(plugin.public())
        for plugin in PLUGIN_REGISTRY.all()
    ]


@router.post(
    "/training-jobs",
    dependencies=[
        Depends(enforce_mutation_rate_limit),
        Depends(require_training_worker_available),
    ],
    response_model=TrainingJobSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an allowlisted model training job",
    responses={
        **_JOB_SUBMISSION_RESPONSES,
        422: {"description": "Invalid algorithm configuration."},
    },
)
async def submit_generic_training_job(
    payload: GenericTrainingJobRequest,
    response: Response,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[TrainingJobService, Depends(get_training_job_service)],
    dataset_service: Annotated[DatasetService, Depends(get_dataset_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", max_length=128),
    ] = None,
) -> TrainingJobSubmissionResponse:
    """Validate a plugin request, persist it, and enqueue only its UUID."""
    dataset_snapshot = None
    if payload.dataset_version_id is not None:
        try:
            dataset_snapshot = await dataset_service.resolve_training_snapshot(
                payload.dataset_version_id,
                owner_id=current_user.company_id,
            )
        except DatasetNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        except DatasetConflictError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        except DatasetQueueError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        training_features = dataset_snapshot.training_features
        training_targets = dataset_snapshot.training_targets
        evaluation_features = dataset_snapshot.evaluation_features
        evaluation_targets = dataset_snapshot.evaluation_targets
    else:
        assert payload.training_features is not None
        assert payload.training_targets is not None
        assert payload.evaluation_features is not None
        assert payload.evaluation_targets is not None
        training_features = tuple(tuple(row) for row in payload.training_features)
        training_targets = tuple(payload.training_targets)
        evaluation_features = tuple(tuple(row) for row in payload.evaluation_features)
        evaluation_targets = tuple(payload.evaluation_targets)
    try:
        plugin = PLUGIN_REGISTRY.get(payload.algorithm, payload.task_type)
        if payload.task_type is TaskType.CLASSIFICATION and any(
            type(value) is not int for value in (*training_targets, *evaluation_targets)
        ):
            raise ModelPluginError(
                "Classification datasets require integer target labels."
            )
        parameters = dict(plugin.validate_parameters(payload.hyperparameters))
        registered_model_name = (
            payload.registered_model_name
            or build_registered_model_name(
                plugin.key, prefix=settings.ai_default_registered_model_prefix
            )
        )
        common: dict[str, object] = {
            "training_features": training_features,
            "evaluation_features": evaluation_features,
            "dataset_version_id": (
                dataset_snapshot.dataset_version_id if dataset_snapshot else None
            ),
            "dataset_schema_snapshot": (
                dataset_snapshot.schema_snapshot if dataset_snapshot else None
            ),
            "random_seed": payload.random_seed,
            "experiment_name": payload.experiment_name,
            "run_name": payload.run_name,
            "registered_model_name": registered_model_name,
            "tags": payload.tags,
            "model_description": payload.model_description,
        }
        specification: TrainingJobSpec
        if plugin.key.algorithm is AlgorithmType.RANDOM_FOREST:
            if (
                payload.preprocessing.imputer != "none"
                or payload.preprocessing.scaler not in {"auto", "none"}
            ):
                raise ModelPluginError(
                    "Existing Random Forest compatibility models do not support "
                    "explicit preprocessing."
                )
            random_forest_parameters = {
                **parameters,
                "min_samples_split": 2,
                "max_features": (
                    "sqrt" if payload.task_type is TaskType.CLASSIFICATION else 1.0
                ),
                "bootstrap": True,
                "n_jobs": 1,
                "random_state": payload.random_seed,
                "criterion": (
                    "gini"
                    if payload.task_type is TaskType.CLASSIFICATION
                    else "squared_error"
                ),
            }
            if payload.task_type is TaskType.CLASSIFICATION:
                specification = RandomForestClassificationJobSpec(
                    **common,
                    hyperparameters=random_forest_parameters,
                    training_targets=tuple(int(value) for value in training_targets),
                    evaluation_targets=tuple(
                        int(value) for value in evaluation_targets
                    ),
                )
            else:
                specification = RandomForestRegressionJobSpec(
                    **common,
                    hyperparameters=random_forest_parameters,
                    training_targets=tuple(float(value) for value in training_targets),
                    evaluation_targets=tuple(
                        float(value) for value in evaluation_targets
                    ),
                )
        elif payload.task_type is TaskType.CLASSIFICATION:
            specification = PluginClassificationJobSpec(
                **common,
                plugin_id=plugin.id,
                hyperparameters=parameters,
                preprocessing=PreprocessingJobConfig(
                    scaler=payload.preprocessing.scaler,
                    imputer=payload.preprocessing.imputer,
                ),
                training_targets=tuple(int(value) for value in training_targets),
                evaluation_targets=tuple(int(value) for value in evaluation_targets),
            )
        else:
            specification = PluginRegressionJobSpec(
                **common,
                plugin_id=plugin.id,
                hyperparameters=parameters,
                preprocessing=PreprocessingJobConfig(
                    scaler=payload.preprocessing.scaler,
                    imputer=payload.preprocessing.imputer,
                ),
                training_targets=tuple(float(value) for value in training_targets),
                evaluation_targets=tuple(float(value) for value in evaluation_targets),
            )
    except ModelPluginError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail="Training data is incompatible with the selected algorithm.",
        ) from exc
    submission = await _submit(
        service=service,
        current_user=current_user,
        specification=specification,
        idempotency_key=idempotency_key,
    )
    if not submission.created:
        response.status_code = status.HTTP_200_OK
    else:
        await audit.record(
            company_id=current_user.company_id,
            actor=current_user,
            action="training.submitted",
            resource_type="training_job",
            resource_id=submission.job.id,
            result="success",
            metadata={
                "algorithm": submission.job.key.algorithm.value,
                "task_type": submission.job.key.task_type.value,
            },
        )
    return _submission_response(submission.job)


@router.post(
    "/training-jobs/random-forest/regression",
    dependencies=[
        Depends(enforce_mutation_rate_limit),
        Depends(require_training_worker_available),
    ],
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
    audit: Annotated[AuditService, Depends(get_audit_service)],
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
    else:
        await audit.record(
            company_id=current_user.company_id,
            actor=current_user,
            action="training.submitted",
            resource_type="training_job",
            resource_id=submission.job.id,
            result="success",
            metadata={"algorithm": "random_forest", "task_type": "regression"},
        )
    return _submission_response(submission.job)


@router.post(
    "/training-jobs/random-forest/classification",
    dependencies=[
        Depends(enforce_mutation_rate_limit),
        Depends(require_training_worker_available),
    ],
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
    audit: Annotated[AuditService, Depends(get_audit_service)],
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
    else:
        await audit.record(
            company_id=current_user.company_id,
            actor=current_user,
            action="training.submitted",
            resource_type="training_job",
            resource_id=submission.job.id,
            result="success",
            metadata={"algorithm": "random_forest", "task_type": "classification"},
        )
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
    "/training-jobs/{job_id}/evaluation",
    response_model=dict[str, object],
    summary="Evaluate a completed training job on its held-out sample",
    responses={
        **_JOB_READ_RESPONSES,
        409: {"description": "The job has not completed."},
    },
)
async def get_training_job_evaluation(
    job_id: UUID,
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[TrainingJobService, Depends(get_training_job_service)],
    registry: Annotated[BaseModelRegistry, Depends(get_ai_model_registry)],
    loader: Annotated[
        BaseRegisteredModelLoader, Depends(get_ai_registered_model_loader)
    ],
) -> dict[str, object]:
    """Return bounded chart and explanation data derived from held-out rows."""
    try:
        job = await service.get_authorized(
            job_id=job_id,
            current_user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
        )
    except TrainingJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if (
        job.status is not TrainingJobStatus.SUCCEEDED
        or job.registered_model_version is None
    ):
        raise HTTPException(
            status_code=409,
            detail="Training must succeed before evaluation is available.",
        )
    try:
        version = registry.resolve(
            job.registered_model_name, job.registered_model_version
        )
        if version.key != job.key:
            raise HTTPException(
                status_code=409,
                detail="Registered model metadata does not match the training job.",
            )
        model = loader.load(version, object)
        plugin = PLUGIN_REGISTRY.get_by_key(job.key)
        specification = job.specification
        feature_values = np.asarray(specification.evaluation_features, dtype=np.float64)
        if job.key.task_type is TaskType.CLASSIFICATION:
            target_values = np.asarray(specification.evaluation_targets, dtype=np.int64)
        else:
            target_values = np.asarray(
                specification.evaluation_targets, dtype=np.float64
            )
        return build_evaluation_payload(
            plugin=plugin,
            model=model,
            features=feature_values,
            targets=target_values,
            random_seed=specification.random_seed or 17,
        )
    except HTTPException:
        raise
    except ModelRegistryValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RegisteredModelVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ModelRegistryError, RegisteredModelLoadError) as exc:
        raise HTTPException(
            status_code=502, detail="The registered model could not be evaluated."
        ) from exc
    except (ModelPluginError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail="The held-out evaluation data is incompatible with this model.",
        ) from exc


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
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> TrainingJobResponse:
    """Persist cancellation only before a worker claims the job."""
    try:
        cancelled = await service.cancel(
            job_id=job_id,
            current_user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
        )
    except TrainingJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TrainingJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="training.cancelled",
        resource_type="training_job",
        resource_id=job_id,
        result="success",
    )
    return _job_response(cancelled)


@router.post(
    "/models/{registered_model_name}/versions/{version}/promotions/challenger",
    dependencies=[Depends(enforce_mutation_rate_limit)],
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
    audit: Annotated[AuditService, Depends(get_audit_service)],
    payload: Annotated[ModelPromotionBody, Body()],
) -> ModelPromotionResponse:
    """Assign challenger after task policy evaluation."""
    response = await _promote(
        registered_model_name=registered_model_name,
        version=version,
        target_alias=ModelAlias.CHALLENGER,
        payload=payload,
        current_user=current_user,
        service=service,
    )
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="model.alias_changed",
        resource_type="model_version",
        resource_id=f"{registered_model_name}:{version}",
        result="success",
        metadata={"alias": "challenger"},
    )
    return response


@router.post(
    "/models/{registered_model_name}/versions/{version}/promotions/champion",
    dependencies=[Depends(enforce_mutation_rate_limit)],
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
    audit: Annotated[AuditService, Depends(get_audit_service)],
    payload: Annotated[ModelPromotionBody, Body()],
) -> ModelPromotionResponse:
    """Assign champion only through an explicit admin request."""
    response = await _promote(
        registered_model_name=registered_model_name,
        version=version,
        target_alias=ModelAlias.CHAMPION,
        payload=payload,
        current_user=current_user,
        service=service,
    )
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="model.alias_changed",
        resource_type="model_version",
        resource_id=f"{registered_model_name}:{version}",
        result="success",
        metadata={"alias": "champion"},
    )
    return response


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
    if isinstance(
        specification,
        (PluginRegressionJobSpec, PluginClassificationJobSpec),
    ):
        key = specification.plugin_key()
    else:
        key = random_forest_key(
            TaskType.REGRESSION
            if isinstance(specification, RandomForestRegressionJobSpec)
            else TaskType.CLASSIFICATION
        )
    try:
        return await service.submit(
            requested_by_user_id=current_user.id,
            key=key,
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
        dataset_version_id=job.dataset_version_id,
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
