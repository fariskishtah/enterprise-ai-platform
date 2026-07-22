"""Authenticated management API for persisted AutoML studies and trials."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import require_roles
from app.dependencies.database import get_db_session
from app.dependencies.rate_limit import enforce_mutation_rate_limit
from app.ml.automl.champion import ChampionCandidate, rank_champions
from app.ml.automl.models import AutoMLStudyStatus, AutoMLTrialStatus
from app.ml.automl.queue import AutoMLQueue, DramatiqAutoMLQueue
from app.ml.automl.search_space import (
    CategoricalSearchParameter,
    FloatSearchParameter,
    IntegerSearchParameter,
)
from app.ml.domain import TaskType
from app.ml.plugins import create_default_plugin_registry
from app.models.automl import AutoMLStudy, AutoMLTrial
from app.models.user import User, UserRole
from app.repositories.automl import AutoMLRepository
from app.schemas.automl import (
    AutoMLAlgorithmMetadataResponse,
    AutoMLCancelResponse,
    AutoMLLeaderboardEntryResponse,
    AutoMLSearchParameterResponse,
    AutoMLStudyCreateRequest,
    AutoMLStudyDetailResponse,
    AutoMLStudyListResponse,
    AutoMLStudySubmissionResponse,
    AutoMLStudySummaryResponse,
    AutoMLTrialDetailResponse,
    AutoMLTrialListResponse,
    AutoMLTrialSummaryResponse,
)
from app.services.automl import AutoMLConflictError, AutoMLNotFoundError, AutoMLService

router = APIRouter(prefix="/ai/automl", tags=["AI AutoML"])
_AUTH: dict[int | str, dict[str, object]] = {
    401: {"description": "Authentication required."},
    403: {"description": "Insufficient role."},
}


def _service(session: AsyncSession) -> AutoMLService:
    return AutoMLService(AutoMLRepository(session))


def get_automl_queue() -> AutoMLQueue:
    return DramatiqAutoMLQueue()


@router.get(
    "/algorithms", response_model=list[AutoMLAlgorithmMetadataResponse], responses=_AUTH
)
def algorithms(
    _user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))]
) -> list[AutoMLAlgorithmMetadataResponse]:
    result: list[AutoMLAlgorithmMetadataResponse] = []
    for plugin in create_default_plugin_registry().all():
        space = plugin.automl_search_space
        if space is None:
            continue
        parameters: list[AutoMLSearchParameterResponse] = []
        for parameter in space.parameters:
            common: dict[str, object] = {
                "name": parameter.name,
                "kind": parameter.kind,
                "default": parameter.default,
            }
            if isinstance(parameter, (IntegerSearchParameter, FloatSearchParameter)):
                common.update(
                    low=parameter.low,
                    high=parameter.high,
                    step=parameter.step,
                    log_scale=parameter.log_scale,
                )
            elif isinstance(parameter, CategoricalSearchParameter):
                common["choices"] = list(parameter.choices)
            parameters.append(AutoMLSearchParameterResponse.model_validate(common))
        result.append(
            AutoMLAlgorithmMetadataResponse(
                id=plugin.id,
                display_name=plugin.display_name,
                task_type=space.task_type,
                probability_support=space.probability_support,
                parameters=parameters,
            )
        )
    return result


@router.post(
    "/studies",
    response_model=AutoMLStudySubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
    responses={**_AUTH, 409: {"description": "Idempotency conflict."}},
)
async def create_study(
    payload: AutoMLStudyCreateRequest,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    queue: Annotated[AutoMLQueue, Depends(get_automl_queue)],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", max_length=128)
    ] = None,
) -> AutoMLStudySubmissionResponse:
    try:
        submission = await _service(session).create_study(
            owner_id=current_user.id,
            specification=payload.to_specification(),
            idempotency_key=idempotency_key,
        )
    except AutoMLConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    study = submission.study
    if submission.created:
        try:
            message_id = queue.enqueue_study(study.id)
            updated = await AutoMLRepository(session).set_study_queue_identifier(
                study_id=study.id,
                queue_message_id=message_id,
                expected_version=study.state_version,
            )
            if updated is not None:
                await session.commit()
                study = updated
            else:
                await session.rollback()
        except Exception:
            await session.rollback()
    return AutoMLStudySubmissionResponse(
        study_id=study.id,
        status=study.status,
        submitted_at=study.created_at,
        status_url=f"/ai/automl/studies/{study.id}",
        created=submission.created,
    )


@router.get("/studies", response_model=AutoMLStudyListResponse, responses=_AUTH)
async def list_studies(
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    study_status: Annotated[AutoMLStudyStatus | None, Query(alias="status")] = None,
    task_type: TaskType | None = None,
    plugin_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    requester_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AutoMLStudyListResponse:
    if requester_id is not None and current_user.role is not UserRole.ADMIN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only administrators may filter by requester."
        )
    page = await _service(session).list_studies(
        user_id=current_user.id,
        is_admin=current_user.role is UserRole.ADMIN,
        status=study_status,
        task_type=task_type,
        plugin_id=plugin_id,
        requester_id=requester_id,
        limit=limit,
        offset=offset,
    )
    return AutoMLStudyListResponse(
        items=[_study_summary(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/studies/{study_id}",
    response_model=AutoMLStudyDetailResponse,
    responses={**_AUTH, 404: {"description": "Study not found."}},
)
async def get_study(
    study_id: UUID,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AutoMLStudyDetailResponse:
    try:
        value = await _service(session).get_study(
            study_id=study_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
        )
    except AutoMLNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _study_detail(value)


@router.get(
    "/studies/{study_id}/trials",
    response_model=AutoMLTrialListResponse,
    responses={**_AUTH, 404: {"description": "Study not found."}},
)
async def list_trials(
    study_id: UUID,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    trial_status: Annotated[AutoMLTrialStatus | None, Query(alias="status")] = None,
    plugin_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    order: Literal["trial_number", "metric_desc"] = "trial_number",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AutoMLTrialListResponse:
    try:
        page = await _service(session).list_trials(
            study_id=study_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
            status=trial_status,
            plugin_id=plugin_id,
            limit=limit,
            offset=offset,
            metric_descending=order == "metric_desc",
        )
    except AutoMLNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return AutoMLTrialListResponse(
        items=[_trial_summary(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/studies/{study_id}/trials/{trial_id}",
    response_model=AutoMLTrialDetailResponse,
    responses={**_AUTH, 404: {"description": "Trial not found."}},
)
async def get_trial(
    study_id: UUID,
    trial_id: UUID,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AutoMLTrialDetailResponse:
    try:
        value = await _service(session).get_trial(
            study_id=study_id,
            trial_id=trial_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
        )
    except AutoMLNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return AutoMLTrialDetailResponse(
        **_trial_summary(value).model_dump(),
        parameters=value.parameters,
        attempt_count=value.attempt_count,
        max_attempts=value.max_attempts,
        fold_metrics=value.fold_metrics,
        aggregate_metrics=value.aggregate_metrics,
        safe_error_message=value.safe_error_message,
    )


@router.post(
    "/studies/{study_id}/cancel",
    response_model=AutoMLCancelResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
    responses={
        **_AUTH,
        404: {"description": "Study not found."},
        409: {"description": "Concurrent state conflict."},
    },
)
async def cancel_study(
    study_id: UUID,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AutoMLCancelResponse:
    try:
        value, outcome = await _service(session).cancel(
            study_id=study_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
        )
    except AutoMLNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except AutoMLConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return AutoMLCancelResponse(
        study_id=value.id,
        status=value.status,
        cancellation=outcome,
        cancel_requested_at=value.cancel_requested_at,
        cancelled_at=value.cancelled_at,
    )


def _study_summary(value: AutoMLStudy) -> AutoMLStudySummaryResponse:
    return AutoMLStudySummaryResponse(
        study_id=value.id,
        requested_by_user_id=value.requested_by_user_id,
        task_type=value.task_type,
        status=value.status,
        primary_metric=value.primary_metric,
        metric_direction=value.metric_direction,
        plugin_ids=value.plugin_ids,
        trial_budget=value.trial_budget,
        created_at=value.created_at,
        started_at=value.started_at,
        finished_at=value.finished_at,
        cancel_requested_at=value.cancel_requested_at,
    )


def _study_detail(value: AutoMLStudy) -> AutoMLStudyDetailResponse:
    data = value.data_specification
    safe_data = {
        key: data[key]
        for key in (
            "training_data_fingerprint",
            "evaluation_data_fingerprint",
            "training_row_count",
            "evaluation_row_count",
            "feature_count",
        )
        if key in data
    }
    return AutoMLStudyDetailResponse(
        **_study_summary(value).model_dump(),
        random_seed=value.random_seed,
        sampler_type=value.sampler_type,
        search_spaces=value.search_spaces,
        preprocessing=value.preprocessing,
        data_specification=safe_data,
        cross_validation_folds=value.cross_validation_folds,
        time_budget_seconds=value.time_budget_seconds,
        per_trial_timeout_seconds=value.per_trial_timeout_seconds,
        max_concurrent_trials=value.max_concurrent_trials,
        register_champion=value.register_champion,
        registered_model_name=value.registered_model_name,
        best_trial_id=value.best_trial_id,
        champion_training_job_id=value.champion_training_job_id,
        safe_error_message=value.safe_error_message,
    )


def _trial_summary(value: AutoMLTrial) -> AutoMLTrialSummaryResponse:
    return AutoMLTrialSummaryResponse(
        trial_id=value.id,
        study_id=value.study_id,
        trial_number=value.trial_number,
        plugin_id=value.plugin_id,
        status=value.status,
        primary_metric_value=value.primary_metric_value,
        duration_seconds=value.duration_seconds,
        created_at=value.created_at,
        started_at=value.started_at,
        finished_at=value.finished_at,
    )


@router.get(
    "/studies/{study_id}/leaderboard",
    response_model=list[AutoMLLeaderboardEntryResponse],
    responses={**_AUTH, 404: {"description": "Study not found."}},
)
async def get_leaderboard(
    study_id: UUID,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[AutoMLLeaderboardEntryResponse]:
    service = _service(session)
    try:
        study = await service.get_study(
            study_id=study_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
        )
        page = await service.list_trials(
            study_id=study_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
            status=AutoMLTrialStatus.SUCCEEDED,
            plugin_id=None,
            limit=100,
            offset=0,
            metric_descending=False,
        )
    except AutoMLNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    by_id = {trial.id: trial for trial in page.items}
    candidates = tuple(
        ChampionCandidate(
            trial.id,
            trial.trial_number,
            trial.primary_metric_value,
            float(
                (trial.aggregate_metrics or {}).get(
                    f"{study.primary_metric}_std", 1e308
                )
            ),
        )
        for trial in page.items
        if trial.primary_metric_value is not None
    )
    return [
        AutoMLLeaderboardEntryResponse(
            rank=index,
            trial_id=candidate.trial_id,
            trial_number=candidate.trial_number,
            plugin_id=by_id[candidate.trial_id].plugin_id,
            status=by_id[candidate.trial_id].status,
            primary_metric_value=candidate.primary_metric_value,
            metric_standard_deviation=(
                (by_id[candidate.trial_id].aggregate_metrics or {}).get(
                    f"{study.primary_metric}_std"
                )
            ),
            duration_seconds=by_id[candidate.trial_id].duration_seconds,
            parameters=by_id[candidate.trial_id].parameters,
        )
        for index, candidate in enumerate(
            rank_champions(candidates, study.metric_direction), start=1
        )
    ]
