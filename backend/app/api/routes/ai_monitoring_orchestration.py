"""Authenticated APIs for persisted monitoring orchestration and outcomes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query

from app.dependencies.auth import require_roles
from app.dependencies.rate_limit import enforce_mutation_rate_limit
from app.dependencies.services import (
    get_monitoring_alert_service,
    get_monitoring_evaluation_service,
    get_prediction_outcome_service,
)
from app.ml.domain import TaskType
from app.ml.monitoring.alert_service import MonitoringAlertService
from app.ml.monitoring.evaluation_models import (
    ClassificationPerformanceSummary,
    ModelMonitoringEvaluation,
    MonitoringAlert,
    MonitoringAlertSeverity,
    MonitoringAlertStatus,
    MonitoringEvaluationStatus,
    MonitoringEvaluationTrigger,
    PredictionOutcome,
    RegressionPerformanceSummary,
)
from app.ml.monitoring.evaluation_service import MonitoringEvaluationService
from app.ml.monitoring.exceptions import (
    MonitoringNotFoundError,
    MonitoringPersistenceError,
    MonitoringPreconditionError,
    MonitoringWindowValidationError,
    PredictionMonitoringError,
)
from app.ml.monitoring.outcome_service import PredictionOutcomeService
from app.ml.registry import (
    ModelRegistryError,
    ModelRegistryValidationError,
    RegisteredModelVersionNotFoundError,
)
from app.models.user import User, UserRole
from app.schemas.ai_monitoring_orchestration import (
    ClassificationPerformanceResponse,
    ManualMonitoringEvaluationBody,
    MonitoringAlertPageResponse,
    MonitoringAlertResponse,
    MonitoringEvaluationPageResponse,
    MonitoringEvaluationResponse,
    PerformanceResponse,
    PredictionOutcomeBody,
    PredictionOutcomeResponse,
    RegressionPerformanceResponse,
)

router = APIRouter(prefix="/ai/monitoring", tags=["ai-monitoring"])
_MODEL_NAME = Path(min_length=3, max_length=128, pattern=r"^[a-z][a-z0-9_]{2,127}$")
_VERSION = Path(min_length=1, max_length=128, pattern=r"^[1-9][0-9]*$")
_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"description": "Missing or invalid access token."},
    403: {"description": "The current role is not authorized."},
    404: {"description": "The requested monitoring record was not found."},
    409: {"description": "Monitoring state conflicts with the requested operation."},
    422: {"description": "The bounded request is invalid."},
    503: {"description": "Monitoring persistence is unavailable."},
}


@router.get(
    "/evaluations",
    response_model=MonitoringEvaluationPageResponse,
    responses=_RESPONSES,
    summary="List persisted model monitoring evaluations",
)
async def list_monitoring_evaluations(
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[
        MonitoringEvaluationService, Depends(get_monitoring_evaluation_service)
    ],
    registered_model_name: Annotated[str | None, Query(max_length=128)] = None,
    model_version: Annotated[str | None, Query(pattern=r"^[1-9][0-9]*$")] = None,
    overall_status: MonitoringEvaluationStatus | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> MonitoringEvaluationPageResponse:
    try:
        page = await service.list(
            registered_model_name=registered_model_name,
            model_version=model_version,
            overall_status=overall_status,
            start_at=start_at,
            end_at=end_at,
            limit=limit,
            offset=offset,
        )
    except (PredictionMonitoringError, ModelRegistryError) as exc:
        _translate(exc)
    return MonitoringEvaluationPageResponse(
        items=tuple(_evaluation(item) for item in page.items),
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/evaluations/{evaluation_id}",
    response_model=MonitoringEvaluationResponse,
    responses=_RESPONSES,
    summary="Get one persisted monitoring evaluation",
)
async def get_monitoring_evaluation(
    evaluation_id: UUID,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[
        MonitoringEvaluationService, Depends(get_monitoring_evaluation_service)
    ],
) -> MonitoringEvaluationResponse:
    try:
        return _evaluation(await service.get(evaluation_id))
    except (PredictionMonitoringError, ModelRegistryError) as exc:
        _translate(exc)


@router.get(
    "/models/{registered_model_name}/versions/{model_version}/evaluations",
    response_model=MonitoringEvaluationPageResponse,
    responses=_RESPONSES,
    summary="Get persisted evaluation history for an exact model version",
)
async def get_monitoring_evaluation_history(
    registered_model_name: Annotated[str, _MODEL_NAME],
    model_version: Annotated[str, _VERSION],
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[
        MonitoringEvaluationService, Depends(get_monitoring_evaluation_service)
    ],
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> MonitoringEvaluationPageResponse:
    try:
        page = await service.list(
            registered_model_name=registered_model_name,
            model_version=model_version,
            overall_status=None,
            start_at=start_at,
            end_at=end_at,
            limit=limit,
            offset=offset,
        )
    except (PredictionMonitoringError, ModelRegistryError) as exc:
        _translate(exc)
    return MonitoringEvaluationPageResponse(
        items=tuple(_evaluation(item) for item in page.items),
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/models/{registered_model_name}/versions/{model_version}/evaluations",
    dependencies=[Depends(enforce_mutation_rate_limit)],
    response_model=MonitoringEvaluationResponse,
    responses=_RESPONSES,
    summary="Manually evaluate an exact registered model version",
)
async def trigger_monitoring_evaluation(
    registered_model_name: Annotated[str, _MODEL_NAME],
    model_version: Annotated[str, _VERSION],
    body: ManualMonitoringEvaluationBody,
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[
        MonitoringEvaluationService, Depends(get_monitoring_evaluation_service)
    ],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", max_length=128)
    ] = None,
) -> MonitoringEvaluationResponse:
    try:
        evaluation = await service.evaluate(
            registered_model_name=registered_model_name,
            version_or_alias=model_version,
            window_start=body.window_start,
            window_end=body.window_end,
            trigger=MonitoringEvaluationTrigger.MANUAL,
            idempotency_key=idempotency_key,
        )
    except (PredictionMonitoringError, ModelRegistryError) as exc:
        _translate(exc)
    return _evaluation(evaluation)


@router.get(
    "/models/{registered_model_name}/versions/{model_version}/status/latest",
    response_model=MonitoringEvaluationResponse,
    responses=_RESPONSES,
    summary="Get latest persisted monitoring status for an exact model version",
)
async def get_latest_monitoring_status(
    registered_model_name: Annotated[str, _MODEL_NAME],
    model_version: Annotated[str, _VERSION],
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[
        MonitoringEvaluationService, Depends(get_monitoring_evaluation_service)
    ],
) -> MonitoringEvaluationResponse:
    try:
        return _evaluation(
            await service.latest(
                registered_model_name=registered_model_name,
                model_version=model_version,
            )
        )
    except (PredictionMonitoringError, ModelRegistryError) as exc:
        _translate(exc)


@router.get(
    "/alerts",
    response_model=MonitoringAlertPageResponse,
    responses=_RESPONSES,
    summary="List deduplicated internal monitoring alerts",
)
async def list_monitoring_alerts(
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[MonitoringAlertService, Depends(get_monitoring_alert_service)],
    registered_model_name: Annotated[str | None, Query(max_length=128)] = None,
    model_version: Annotated[str | None, Query(pattern=r"^[1-9][0-9]*$")] = None,
    severity: MonitoringAlertSeverity | None = None,
    status: MonitoringAlertStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> MonitoringAlertPageResponse:
    try:
        page = await service.list(
            registered_model_name=registered_model_name,
            model_version=model_version,
            severity=severity,
            status=status,
            limit=limit,
            offset=offset,
        )
    except PredictionMonitoringError as exc:
        _translate(exc)
    return MonitoringAlertPageResponse(
        items=tuple(_alert(item) for item in page.items),
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/alerts/{alert_id}",
    response_model=MonitoringAlertResponse,
    responses=_RESPONSES,
    summary="Get one internal monitoring alert",
)
async def get_monitoring_alert(
    alert_id: UUID,
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[MonitoringAlertService, Depends(get_monitoring_alert_service)],
) -> MonitoringAlertResponse:
    try:
        return _alert(await service.get(alert_id))
    except PredictionMonitoringError as exc:
        _translate(exc)


@router.post(
    "/alerts/{alert_id}/acknowledge",
    dependencies=[Depends(enforce_mutation_rate_limit)],
    response_model=MonitoringAlertResponse,
    responses=_RESPONSES,
    summary="Acknowledge an open monitoring alert",
)
async def acknowledge_monitoring_alert(
    alert_id: UUID,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[MonitoringAlertService, Depends(get_monitoring_alert_service)],
) -> MonitoringAlertResponse:
    try:
        return _alert(await service.acknowledge(alert_id, current_user.id))
    except PredictionMonitoringError as exc:
        _translate(exc)


@router.post(
    "/alerts/{alert_id}/resolve",
    dependencies=[Depends(enforce_mutation_rate_limit)],
    response_model=MonitoringAlertResponse,
    responses=_RESPONSES,
    summary="Administratively resolve a monitoring alert",
)
async def resolve_monitoring_alert(
    alert_id: UUID,
    _current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[MonitoringAlertService, Depends(get_monitoring_alert_service)],
) -> MonitoringAlertResponse:
    try:
        return _alert(await service.resolve(alert_id))
    except PredictionMonitoringError as exc:
        _translate(exc)


@router.put(
    "/prediction-events/{prediction_event_id}/outcome",
    response_model=PredictionOutcomeResponse,
    responses=_RESPONSES,
    summary="Submit or update one observed prediction outcome",
)
async def upsert_prediction_outcome(
    prediction_event_id: UUID,
    body: PredictionOutcomeBody,
    _current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[
        PredictionOutcomeService, Depends(get_prediction_outcome_service)
    ],
) -> PredictionOutcomeResponse:
    try:
        outcome = await service.upsert(
            prediction_event_id=prediction_event_id,
            actual_value=body.actual_value,
            observed_at=body.observed_at,
            source=body.source,
            label_maturity_at=body.label_maturity_at,
            safe_metadata=body.safe_metadata,
            external_reference_key=body.external_reference_key,
        )
    except PredictionMonitoringError as exc:
        _translate(exc)
    return _outcome(outcome)


@router.get(
    "/models/{registered_model_name}/versions/{model_version}/performance",
    response_model=PerformanceResponse,
    responses=_RESPONSES,
    summary="Get a bounded performance summary from mature outcomes",
)
async def get_model_performance(
    registered_model_name: Annotated[str, _MODEL_NAME],
    model_version: Annotated[str, _VERSION],
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[
        PredictionOutcomeService, Depends(get_prediction_outcome_service)
    ],
) -> PerformanceResponse:
    try:
        summary = await service.performance_summary(
            registered_model_name=registered_model_name, model_version=model_version
        )
    except PredictionMonitoringError as exc:
        _translate(exc)
    if isinstance(summary, RegressionPerformanceSummary):
        return RegressionPerformanceResponse(
            registered_model_name=summary.registered_model_name,
            model_version=summary.model_version,
            task_type=TaskType.REGRESSION,
            evaluated_sample_count=summary.evaluated_sample_count,
            mae=summary.mae,
            rmse=summary.rmse,
            mean_prediction_bias=summary.mean_prediction_bias,
        )
    if isinstance(summary, ClassificationPerformanceSummary):
        return ClassificationPerformanceResponse(
            registered_model_name=summary.registered_model_name,
            model_version=summary.model_version,
            task_type=TaskType.CLASSIFICATION,
            evaluated_sample_count=summary.evaluated_sample_count,
            accuracy=summary.accuracy,
            precision=summary.precision,
            recall=summary.recall,
            f1=summary.f1,
            false_negative_rate=summary.false_negative_rate,
            true_positive_count=summary.true_positive_count,
            true_negative_count=summary.true_negative_count,
            false_positive_count=summary.false_positive_count,
            false_negative_count=summary.false_negative_count,
        )
    raise AssertionError("Unsupported performance summary.")


def _evaluation(value: ModelMonitoringEvaluation) -> MonitoringEvaluationResponse:
    return MonitoringEvaluationResponse(
        id=value.id,
        registered_model_name=value.registered_model_name,
        model_version=value.model_version,
        model_alias=value.model_alias,
        algorithm=value.key.algorithm,
        task_type=value.key.task_type,
        window_start=value.window_start,
        window_end=value.window_end,
        evaluated_sample_count=value.evaluated_sample_count,
        successful_prediction_count=value.successful_prediction_count,
        failed_prediction_count=value.failed_prediction_count,
        data_quality_status=value.data_quality_status,
        feature_drift_status=value.feature_drift_status,
        prediction_drift_status=value.prediction_drift_status,
        operational_health_status=value.operational_health_status,
        overall_status=value.overall_status,
        report_schema_version=value.report_schema_version,
        report=dict(value.report),
        warning_count=value.warning_count,
        critical_count=value.critical_count,
        trigger=value.trigger,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _alert(value: MonitoringAlert) -> MonitoringAlertResponse:
    return MonitoringAlertResponse(
        id=value.id,
        alert_type=value.alert_type,
        severity=value.severity,
        registered_model_name=value.registered_model_name,
        model_version=value.model_version,
        monitoring_evaluation_id=value.monitoring_evaluation_id,
        title=value.title,
        safe_summary=value.safe_summary,
        status=value.status,
        first_detected_at=value.first_detected_at,
        last_detected_at=value.last_detected_at,
        occurrence_count=value.occurrence_count,
        acknowledged_at=value.acknowledged_at,
        acknowledged_by_user_id=value.acknowledged_by_user_id,
        resolved_at=value.resolved_at,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _outcome(value: PredictionOutcome) -> PredictionOutcomeResponse:
    return PredictionOutcomeResponse(
        id=value.id,
        prediction_event_id=value.prediction_event_id,
        outcome_type=value.outcome_type,
        actual_value=value.actual_value,
        observed_at=value.observed_at,
        source=value.source,
        label_maturity_at=value.label_maturity_at,
        safe_metadata=dict(value.safe_metadata),
        external_reference_key=value.external_reference_key,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _translate(error: Exception) -> NoReturn:
    if isinstance(
        error, (MonitoringNotFoundError, RegisteredModelVersionNotFoundError)
    ):
        status = 404
    elif isinstance(error, MonitoringPreconditionError):
        status = 409
    elif isinstance(
        error, (MonitoringWindowValidationError, ModelRegistryValidationError)
    ):
        status = 422
    elif isinstance(error, MonitoringPersistenceError):
        status = 503
    else:
        status = 502
    detail = (
        str(error)
        if isinstance(error, PredictionMonitoringError)
        else "The external model registry operation failed."
    )
    raise HTTPException(status_code=status, detail=detail) from error
