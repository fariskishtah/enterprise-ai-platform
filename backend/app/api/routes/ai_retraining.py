"""Governed APIs for explicit controlled model retraining."""

from __future__ import annotations

from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.dependencies.auth import require_roles
from app.dependencies.operational import require_training_worker_available
from app.dependencies.rate_limit import enforce_mutation_rate_limit
from app.dependencies.services import get_audit_service, get_retraining_service
from app.ml.retraining import (
    CandidateComparison,
    RetrainingAuditRecord,
    RetrainingDecision,
    RetrainingDependencyError,
    RetrainingError,
    RetrainingNotFoundError,
    RetrainingPersistenceError,
    RetrainingPolicy,
    RetrainingRegistryError,
    RetrainingRequest,
    RetrainingValidationError,
)
from app.ml.retraining.service import RetrainingEvaluationResult, RetrainingService
from app.models.user import User, UserRole
from app.schemas.ai_retraining import (
    CandidateComparisonResponse,
    CooldownResponse,
    ManualRetrainingBody,
    MetricComparisonResponse,
    QuotaResponse,
    RetrainingAuditPageResponse,
    RetrainingAuditResponse,
    RetrainingDecisionResponse,
    RetrainingEvaluationBody,
    RetrainingEvaluationResponse,
    RetrainingPolicyBody,
    RetrainingPolicyResponse,
    RetrainingRequestPageResponse,
    RetrainingRequestResponse,
    RetrainingStatusResponse,
)
from app.services.audit import AuditService

router = APIRouter(prefix="/ai/retraining", tags=["ai-retraining"])

_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"description": "A valid bearer access token is required."},
    403: {"description": "The authenticated role is not permitted."},
    404: {
        "description": "The policy, model version, evidence, or request was not found."
    },
    409: {"description": "The retraining state conflicts with this operation."},
    422: {"description": "The policy or retraining request is invalid."},
    502: {"description": "External model-registry resolution failed safely."},
    503: {
        "description": "Retraining persistence, monitoring, or queue is unavailable."
    },
}
_MODEL_NAME = Path(
    min_length=3,
    max_length=128,
    pattern=r"^[a-z][a-z0-9_]{2,127}$",
)
_VERSION = Path(min_length=1, max_length=128)


async def _audit_retraining_decision(
    audit: AuditService,
    actor: User,
    result: RetrainingEvaluationResult,
) -> None:
    approved = result.decision.eligible
    await audit.record(
        company_id=actor.company_id,
        actor=actor,
        action="retraining.approved" if approved else "retraining.rejected",
        resource_type="retraining_request",
        resource_id=(
            result.request.id
            if result.request is not None
            else result.decision.existing_request_id
        ),
        result="success",
        metadata={
            "decision": result.decision.status.value,
            "request_created": result.request is not None,
        },
    )


@router.get(
    "/policies",
    response_model=tuple[RetrainingPolicyResponse, ...],
    responses=_RESPONSES,
    summary="List controlled retraining policies",
)
async def list_policies(
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[RetrainingService, Depends(get_retraining_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> tuple[RetrainingPolicyResponse, ...]:
    try:
        policies = await service.list_policies(limit=limit, offset=offset)
    except RetrainingError as exc:
        _translate(exc)
    return tuple(_policy(item) for item in policies)


@router.get(
    "/policies/{registered_model_name}",
    response_model=RetrainingPolicyResponse,
    responses=_RESPONSES,
    summary="Get one model retraining policy",
)
async def get_policy(
    registered_model_name: Annotated[str, _MODEL_NAME],
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[RetrainingService, Depends(get_retraining_service)],
) -> RetrainingPolicyResponse:
    try:
        policy = await service.get_policy(registered_model_name)
    except RetrainingError as exc:
        _translate(exc)
    return _policy(policy)


@router.put(
    "/policies/{registered_model_name}",
    dependencies=[Depends(enforce_mutation_rate_limit)],
    response_model=RetrainingPolicyResponse,
    responses=_RESPONSES,
    summary="Create or replace one model retraining policy",
)
async def put_policy(
    registered_model_name: Annotated[str, _MODEL_NAME],
    body: RetrainingPolicyBody,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[RetrainingService, Depends(get_retraining_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> RetrainingPolicyResponse:
    try:
        policy = await service.put_policy(
            registered_model_name=registered_model_name,
            created_by_user_id=current_user.id,
            enabled=body.enabled,
            allowed_trigger_types=body.allowed_trigger_types,
            minimum_drift_status=body.minimum_drift_status,
            minimum_current_sample_count=body.minimum_current_sample_count,
            cooldown_seconds=body.cooldown_seconds,
            maximum_requests_per_day=body.maximum_requests_per_day,
            maximum_requests_per_week=body.maximum_requests_per_week,
            maximum_active_requests=body.maximum_active_requests,
            require_champion_source=body.require_champion_source,
            allow_truncated_drift=body.allow_truncated_drift,
        )
    except RetrainingError as exc:
        _translate(exc)
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="retraining.policy_changed",
        resource_type="retraining_policy",
        resource_id=policy.id,
        result="success",
        metadata={"enabled": policy.enabled},
    )
    return _policy(policy)


@router.post(
    "/models/{registered_model_name}/versions/{version_or_alias}/evaluate",
    dependencies=[Depends(enforce_mutation_rate_limit)],
    response_model=RetrainingEvaluationResponse,
    responses=_RESPONSES,
    summary="Evaluate an explicit drift window for controlled retraining",
    description=(
        "Admin or engineer role required. Every eligible or blocked decision is "
        "audited; ordinary prediction never invokes this operation."
    ),
)
async def evaluate_retraining(
    registered_model_name: Annotated[str, _MODEL_NAME],
    version_or_alias: Annotated[str, _VERSION],
    body: RetrainingEvaluationBody,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[RetrainingService, Depends(get_retraining_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> RetrainingEvaluationResponse:
    try:
        result = await service.evaluate_automatic(
            registered_model_name=registered_model_name,
            version_or_alias=version_or_alias,
            trigger_type=body.trigger_type,
            start_at=body.start_at,
            end_at=body.end_at,
            minimum_sample_count=body.minimum_sample_count,
            submit_if_eligible=body.submit_if_eligible,
            requested_by_user_id=current_user.id,
        )
    except RetrainingError as exc:
        _translate(exc)
    await _audit_retraining_decision(audit, current_user, result)
    return _evaluation(result)


@router.post(
    "/models/{registered_model_name}/versions/{version_or_alias}/requests",
    dependencies=[
        Depends(enforce_mutation_rate_limit),
        Depends(require_training_worker_available),
    ],
    response_model=RetrainingEvaluationResponse,
    responses=_RESPONSES,
    summary="Request manual retraining from an exact trusted source version",
)
async def request_manual_retraining(
    registered_model_name: Annotated[str, _MODEL_NAME],
    version_or_alias: Annotated[str, _VERSION],
    body: ManualRetrainingBody,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[RetrainingService, Depends(get_retraining_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> RetrainingEvaluationResponse:
    if body.override_cooldown and current_user.role is not UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Only an administrator may override retraining cooldown.",
        )
    try:
        result = await service.request_manual(
            registered_model_name=registered_model_name,
            version_or_alias=version_or_alias,
            reason=body.reason,
            requested_by_user_id=current_user.id,
            override_cooldown=body.override_cooldown,
            requester_is_admin=current_user.role is UserRole.ADMIN,
        )
    except RetrainingError as exc:
        _translate(exc)
    await _audit_retraining_decision(audit, current_user, result)
    return _evaluation(result)


@router.get(
    "/status",
    response_model=RetrainingStatusResponse,
    responses=_RESPONSES,
    summary="Get aggregate controlled retraining status",
    description=(
        "Admin, engineer, or operator role required. Returns global lifecycle "
        "counts without user, trigger, policy, or training-data details."
    ),
)
async def get_retraining_status(
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[RetrainingService, Depends(get_retraining_service)],
) -> RetrainingStatusResponse:
    try:
        total, active, completed, failed = await service.aggregate_status()
    except RetrainingError as exc:
        _translate(exc)
    return RetrainingStatusResponse(
        total_requests=total,
        active_requests=active,
        completed_requests=completed,
        failed_requests=failed,
    )


@router.get(
    "/requests",
    response_model=RetrainingRequestPageResponse,
    responses=_RESPONSES,
    summary="List controlled retraining requests",
)
async def list_requests(
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[RetrainingService, Depends(get_retraining_service)],
    registered_model_name: Annotated[str | None, Query(max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RetrainingRequestPageResponse:
    try:
        page = await service.list_requests(
            registered_model_name=registered_model_name, limit=limit, offset=offset
        )
    except RetrainingError as exc:
        _translate(exc)
    return RetrainingRequestPageResponse(
        items=tuple(_request(item) for item in page.items),
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/requests/{request_id}",
    response_model=RetrainingRequestResponse,
    responses=_RESPONSES,
    summary="Get controlled retraining lineage and execution state",
)
async def get_request(
    request_id: UUID,
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[RetrainingService, Depends(get_retraining_service)],
) -> RetrainingRequestResponse:
    try:
        request = await service.get_request(request_id)
    except RetrainingError as exc:
        _translate(exc)
    return _request(request)


@router.get(
    "/requests/{request_id}/comparison",
    response_model=CandidateComparisonResponse,
    responses=_RESPONSES,
    summary="Get advisory source-versus-candidate metric comparison",
)
async def get_comparison(
    request_id: UUID,
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[RetrainingService, Depends(get_retraining_service)],
) -> CandidateComparisonResponse:
    try:
        request = await service.get_request(request_id)
    except RetrainingError as exc:
        _translate(exc)
    if request.comparison is None:
        raise HTTPException(status_code=404, detail="Candidate comparison not found.")
    return _comparison(request.comparison)


@router.get(
    "/audits",
    response_model=RetrainingAuditPageResponse,
    responses=_RESPONSES,
    summary="List append-only retraining evaluation audits",
)
async def list_audits(
    _current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[RetrainingService, Depends(get_retraining_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RetrainingAuditPageResponse:
    try:
        page = await service.list_audits(limit=limit, offset=offset)
    except RetrainingError as exc:
        _translate(exc)
    return RetrainingAuditPageResponse(
        items=tuple(_audit(item) for item in page.items),
        total=page.total,
        limit=limit,
        offset=offset,
    )


def _policy(value: RetrainingPolicy) -> RetrainingPolicyResponse:
    return RetrainingPolicyResponse(
        **{name: getattr(value, name) for name in RetrainingPolicyResponse.model_fields}
    )


def _decision(value: RetrainingDecision) -> RetrainingDecisionResponse:
    trigger = value.trigger
    return RetrainingDecisionResponse(
        registered_model_name=value.registered_model_name,
        source_model_version=value.source_model_version,
        requested_alias=value.requested_alias,
        trigger_type=trigger.trigger_type,
        trigger_reference=trigger.reference,
        aggregate_status=trigger.aggregate_status,
        matched_event_count=trigger.matched_event_count,
        analyzed_event_count=trigger.analyzed_event_count,
        current_sample_count=trigger.current_sample_count,
        truncated=trigger.truncated,
        analysis_warning=trigger.analysis_warning,
        thresholds=dict(trigger.thresholds),
        decision_status=value.status,
        reasons=value.reasons,
        evaluated_at=value.evaluated_at,
        cooldown=CooldownResponse(
            active=value.cooldown.active,
            started_at=value.cooldown.started_at,
            expires_at=value.cooldown.expires_at,
            remaining_seconds=value.cooldown.remaining_seconds,
        ),
        quota=QuotaResponse(
            requests_today=value.quota.requests_today,
            requests_this_week=value.quota.requests_this_week,
            active_requests=value.quota.active_requests,
            maximum_per_day=value.quota.maximum_per_day,
            maximum_per_week=value.quota.maximum_per_week,
            maximum_active=value.quota.maximum_active,
        ),
        existing_request_id=value.existing_request_id,
    )


def _request(value: RetrainingRequest) -> RetrainingRequestResponse:
    return RetrainingRequestResponse(
        id=value.id,
        registered_model_name=value.registered_model_name,
        source_model_version=value.source_model_version,
        source_training_job_id=value.source_training_job_id,
        algorithm=value.key.algorithm,
        task_type=value.key.task_type,
        trigger_type=value.trigger_type,
        trigger_reference=value.trigger_reference,
        policy_id=value.policy_id,
        decision_status=value.decision_status,
        request_status=value.request_status,
        evaluation_mode=value.evaluation_mode,
        training_job_id=value.training_job_id,
        monitoring_evaluation_id=value.monitoring_evaluation_id,
        resulting_model_version=value.resulting_model_version,
        requested_by_user_id=value.requested_by_user_id,
        reason=value.reason,
        override_used=value.override_used,
        requested_at=value.requested_at,
        started_at=value.started_at,
        completed_at=value.completed_at,
        safe_failure_code=value.safe_failure_code,
        safe_failure_message=value.safe_failure_message,
        comparison=(
            _comparison(value.comparison) if value.comparison is not None else None
        ),
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _comparison(value: CandidateComparison) -> CandidateComparisonResponse:
    return CandidateComparisonResponse(
        status=value.status,
        metrics=tuple(
            MetricComparisonResponse(
                metric=item.metric,
                source_value=item.source_value,
                candidate_value=item.candidate_value,
                higher_is_better=item.higher_is_better,
                outcome=item.outcome,
            )
            for item in value.metrics
        ),
        source_model_version=value.source_model_version,
        candidate_model_version=value.candidate_model_version,
        compared_at=value.compared_at,
    )


def _evaluation(value: RetrainingEvaluationResult) -> RetrainingEvaluationResponse:
    return RetrainingEvaluationResponse(
        decision=_decision(value.decision),
        request=_request(value.request) if value.request is not None else None,
    )


def _audit(value: RetrainingAuditRecord) -> RetrainingAuditResponse:
    return RetrainingAuditResponse(
        id=value.id,
        policy_id=value.policy_id,
        decision=_decision(value.decision),
        evaluated_by_user_id=value.evaluated_by_user_id,
        evaluation_mode=value.evaluation_mode,
        override_used=value.override_used,
        override_reason=value.override_reason,
        created_request_id=value.created_request_id,
        monitoring_evaluation_id=value.monitoring_evaluation_id,
    )


def _translate(exc: RetrainingError) -> NoReturn:
    if isinstance(exc, RetrainingNotFoundError):
        status = 404
    elif isinstance(exc, RetrainingValidationError):
        status = 422
    elif isinstance(exc, RetrainingRegistryError):
        status = 502
    elif isinstance(exc, (RetrainingDependencyError, RetrainingPersistenceError)):
        status = 503
    else:
        status = 409
    raise HTTPException(status_code=status, detail=str(exc)) from exc
