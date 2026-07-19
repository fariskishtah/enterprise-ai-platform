"""Authorized prediction operations, quality, profile, and drift APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.dependencies.auth import require_roles
from app.dependencies.services import get_prediction_monitoring_service
from app.ml.base import TrainerKey
from app.ml.domain import TaskType
from app.ml.monitoring import (
    ClassificationPredictionDrift,
    ClassificationPredictionProfile,
    ClassificationPredictionReferenceProfile,
    ModelDriftReport,
    ModelReferenceProfile,
    MonitoringDataError,
    MonitoringNotFoundError,
    MonitoringPersistenceError,
    MonitoringPreconditionError,
    MonitoringWindowValidationError,
    NumericReferenceProfile,
    NumericSummary,
    PredictionDataQualityReport,
    PredictionEvent,
    PredictionEventStatus,
    PredictionOperationalSummary,
    RegressionPredictionDrift,
    RegressionPredictionProfile,
    RegressionPredictionReferenceProfile,
)
from app.ml.monitoring.service import PredictionMonitoringService
from app.ml.registry import (
    ModelRegistryError,
    ModelRegistryValidationError,
    RegisteredModelVersionNotFoundError,
    RegistryMetadataError,
)
from app.models.user import User, UserRole
from app.schemas.ai import TrainerKeyResponse
from app.schemas.ai_monitoring import (
    ClassificationPredictionDriftResponse,
    ClassificationPredictionProfileResponse,
    ClassificationPredictionReferenceResponse,
    DataQualityIssueResponse,
    DriftThresholdsResponse,
    FeatureDriftResponse,
    FeatureReferenceProfileResponse,
    FeatureRequestProfileResponse,
    ModelDriftResponse,
    ModelReferenceProfileResponse,
    NumericReferenceProfileResponse,
    NumericSummaryResponse,
    PredictionDataQualityResponse,
    PredictionEventPageResponse,
    PredictionEventResponse,
    PredictionOperationalSummaryResponse,
    RegressionPredictionDriftResponse,
    RegressionPredictionProfileResponse,
    RegressionPredictionReferenceResponse,
)

router = APIRouter(prefix="/ai/monitoring", tags=["ai-monitoring"])

_AUTH_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"description": "A valid bearer access token is required."},
    403: {"description": "The authenticated role is not permitted."},
}
_MONITORING_RESPONSES: dict[int | str, dict[str, object]] = {
    **_AUTH_RESPONSES,
    404: {"description": "The model version, profile, or event was not found."},
    409: {"description": "Monitoring data does not satisfy report preconditions."},
    422: {"description": "The model reference or time window is invalid."},
    502: {"description": "External model-registry resolution failed safely."},
    503: {"description": "Prediction monitoring persistence is unavailable."},
}


@router.get(
    "/prediction-events",
    response_model=PredictionEventPageResponse,
    summary="List privacy-preserving prediction events",
    description=(
        "Admin or engineer role required. Returns bounded per-request statistical "
        "summaries without requester IDs, raw feature matrices, or raw predictions."
    ),
    responses=_MONITORING_RESPONSES,
)
async def list_prediction_events(
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[
        PredictionMonitoringService,
        Depends(get_prediction_monitoring_service),
    ],
    registered_model_name: Annotated[
        str | None,
        Query(
            min_length=3,
            max_length=128,
            pattern=r"^[a-z][a-z0-9_]{2,127}$",
        ),
    ] = None,
    resolved_model_version: Annotated[
        str | None,
        Query(min_length=1, max_length=128),
    ] = None,
    task_type: TaskType | None = None,
    event_status: Annotated[
        PredictionEventStatus | None,
        Query(alias="status"),
    ] = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PredictionEventPageResponse:
    """Return a bounded event page with no user-level transport field."""
    try:
        page = await service.list_events(
            registered_model_name=registered_model_name,
            resolved_model_version=resolved_model_version,
            task_type=task_type,
            status=event_status,
            start_at=start_at,
            end_at=end_at,
            limit=limit,
            offset=offset,
        )
    except _MONITORING_EXCEPTIONS as exc:
        _translate(exc)
    return PredictionEventPageResponse(
        items=tuple(_event_response(event) for event in page.items),
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/prediction-events/{event_id}",
    response_model=PredictionEventResponse,
    summary="Get one privacy-preserving prediction event",
    description=(
        "Admin or engineer role required. Requester identity remains internal; "
        "the response exposes only model identity, status, shape, timing, and "
        "statistical summaries."
    ),
    responses=_MONITORING_RESPONSES,
)
async def get_prediction_event(
    event_id: UUID,
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER)),
    ],
    service: Annotated[
        PredictionMonitoringService,
        Depends(get_prediction_monitoring_service),
    ],
) -> PredictionEventResponse:
    """Return one safe event summary."""
    try:
        event = await service.get_event(event_id)
    except _MONITORING_EXCEPTIONS as exc:
        _translate(exc)
    return _event_response(event)


@router.get(
    "/models/{registered_model_name}/versions/{version_or_alias}/operations",
    response_model=PredictionOperationalSummaryResponse,
    summary="Get prediction operational metrics",
    description=(
        "Resolve the supplied exact version or alias once, then calculate bounded "
        "request counts, success/failure rates, latency percentiles, batch sizes, "
        "and safe error-code counts. Totals cover all matching events; percentiles "
        "use the newest 10,000 at most and expose partial-window metadata. The "
        "instance capture-failure diagnostic resets on restart and is neither "
        "window-filtered nor replica-aggregated. Admin, engineer, or operator role "
        "required."
    ),
    responses=_MONITORING_RESPONSES,
)
async def get_prediction_operations(
    registered_model_name: Annotated[str, Path(min_length=3, max_length=128)],
    version_or_alias: Annotated[str, Path(min_length=1, max_length=128)],
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[
        PredictionMonitoringService,
        Depends(get_prediction_monitoring_service),
    ],
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    task_type: TaskType | None = None,
    event_status: Annotated[
        PredictionEventStatus | None,
        Query(alias="status"),
    ] = None,
) -> PredictionOperationalSummaryResponse:
    """Return aggregate operational health for an exact resolved version."""
    try:
        summary = await service.operations(
            registered_model_name=registered_model_name,
            version_or_alias=version_or_alias,
            start_at=start_at,
            end_at=end_at,
            task_type=task_type,
            status=event_status,
        )
    except _MONITORING_EXCEPTIONS as exc:
        _translate(exc)
    return _operations_response(summary)


@router.get(
    "/models/{registered_model_name}/versions/{version_or_alias}/data-quality",
    response_model=PredictionDataQualityResponse,
    summary="Get prediction request data-quality metrics",
    description=(
        "Report rejected-shape signals separately from valid but unusual values, "
        "including constant columns and out-of-reference-range proportions. Analysis "
        "uses the newest 10,000 matching events at most and explicitly reports "
        "truncation. Admin, engineer, or operator role required."
    ),
    responses=_MONITORING_RESPONSES,
)
async def get_prediction_data_quality(
    registered_model_name: Annotated[str, Path(min_length=3, max_length=128)],
    version_or_alias: Annotated[str, Path(min_length=1, max_length=128)],
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[
        PredictionMonitoringService,
        Depends(get_prediction_monitoring_service),
    ],
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> PredictionDataQualityResponse:
    """Return aggregate shape and reference-range observations."""
    try:
        report = await service.data_quality(
            registered_model_name=registered_model_name,
            version_or_alias=version_or_alias,
            start_at=start_at,
            end_at=end_at,
        )
    except _MONITORING_EXCEPTIONS as exc:
        _translate(exc)
    return _data_quality_response(report)


@router.get(
    "/models/{registered_model_name}/versions/{version_or_alias}/drift",
    response_model=ModelDriftResponse,
    summary="Calculate feature and prediction drift",
    description=(
        "Resolve an alias to one exact version and compare a bounded current window "
        "with that version's evaluation profile. Numeric features and regression "
        "outputs use PSI; classification uses predicted-label total variation, not "
        "probability drift. Analysis uses the newest 10,000 matching events at most, "
        "and a partial window is explicitly reported. An insufficient_data status "
        "is a valid report result."
    ),
    responses=_MONITORING_RESPONSES,
)
async def get_model_drift(
    registered_model_name: Annotated[str, Path(min_length=3, max_length=128)],
    version_or_alias: Annotated[str, Path(min_length=1, max_length=128)],
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[
        PredictionMonitoringService,
        Depends(get_prediction_monitoring_service),
    ],
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    minimum_sample_count: Annotated[int | None, Query(ge=1, le=100_000)] = None,
) -> ModelDriftResponse:
    """Return exact-version feature and prediction distribution drift."""
    try:
        report = await service.drift(
            registered_model_name=registered_model_name,
            version_or_alias=version_or_alias,
            start_at=start_at,
            end_at=end_at,
            minimum_sample_count=minimum_sample_count,
        )
    except _MONITORING_EXCEPTIONS as exc:
        _translate(exc)
    return _drift_response(report)


@router.get(
    "/models/{registered_model_name}/versions/{version_or_alias}/reference-profile",
    response_model=ModelReferenceProfileResponse,
    summary="Get an exact-version model reference profile",
    description=(
        "Return immutable evaluation-derived statistics, fixed numeric bins, and "
        "bounded label frequencies. Raw evaluation matrices are never returned. "
        "Admin, engineer, or operator role required."
    ),
    responses=_MONITORING_RESPONSES,
)
async def get_model_reference_profile(
    registered_model_name: Annotated[str, Path(min_length=3, max_length=128)],
    version_or_alias: Annotated[str, Path(min_length=1, max_length=128)],
    _current_user: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER, UserRole.OPERATOR)),
    ],
    service: Annotated[
        PredictionMonitoringService,
        Depends(get_prediction_monitoring_service),
    ],
) -> ModelReferenceProfileResponse:
    """Return the resolved version's immutable held-out-data profile."""
    try:
        profile = await service.reference_profile(
            registered_model_name=registered_model_name,
            version_or_alias=version_or_alias,
        )
    except _MONITORING_EXCEPTIONS as exc:
        _translate(exc)
    return _reference_response(profile)


_MONITORING_EXCEPTIONS = (
    MonitoringDataError,
    MonitoringNotFoundError,
    MonitoringPersistenceError,
    MonitoringPreconditionError,
    MonitoringWindowValidationError,
    ModelRegistryValidationError,
    RegisteredModelVersionNotFoundError,
    RegistryMetadataError,
    ModelRegistryError,
)


def _translate(error: Exception) -> NoReturn:
    if isinstance(error, MonitoringNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, RegisteredModelVersionNotFoundError):
        raise HTTPException(
            status_code=404,
            detail="The requested registered model version was not found.",
        ) from error
    if isinstance(error, MonitoringPreconditionError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, RegistryMetadataError):
        raise HTTPException(
            status_code=409,
            detail="Registered model metadata conflicts with monitoring requirements.",
        ) from error
    if isinstance(
        error, (MonitoringWindowValidationError, ModelRegistryValidationError)
    ):
        raise HTTPException(status_code=422, detail=str(error)) from error
    if isinstance(error, (MonitoringDataError, MonitoringPersistenceError)):
        raise HTTPException(
            status_code=503,
            detail="Prediction monitoring storage is unavailable.",
        ) from error
    raise HTTPException(
        status_code=502,
        detail="An external model service operation failed.",
    ) from error


def _trainer_key(key: TrainerKey) -> TrainerKeyResponse:
    return TrainerKeyResponse(
        algorithm=key.algorithm,
        task_type=key.task_type,
    )


def _numeric(summary: NumericSummary) -> NumericSummaryResponse:
    return NumericSummaryResponse(
        count=summary.count,
        missing_count=summary.missing_count,
        finite_count=summary.finite_count,
        non_finite_count=summary.non_finite_count,
        minimum=summary.minimum,
        maximum=summary.maximum,
        mean=summary.mean,
        standard_deviation=summary.standard_deviation,
        quantiles=dict(summary.quantiles),
    )


def _event_response(event: PredictionEvent) -> PredictionEventResponse:
    prediction = event.prediction_profile
    prediction_response: (
        RegressionPredictionProfileResponse
        | ClassificationPredictionProfileResponse
        | None
    )
    if isinstance(prediction, RegressionPredictionProfile):
        prediction_response = RegressionPredictionProfileResponse(
            summary=_numeric(prediction.summary),
            reference_bin_counts=prediction.reference_bin_counts,
        )
    elif isinstance(prediction, ClassificationPredictionProfile):
        prediction_response = ClassificationPredictionProfileResponse(
            count=prediction.count,
            class_counts=dict(prediction.class_counts),
            other_count=prediction.other_count,
        )
    else:
        prediction_response = None
    return PredictionEventResponse(
        event_id=event.id,
        registered_model_name=event.registered_model_name,
        requested_model_reference=event.requested_model_reference,
        resolved_model_version=event.resolved_model_version,
        resolved_aliases=event.resolved_aliases,
        trainer_key=_trainer_key(event.key),
        status=event.status,
        row_count=event.row_count,
        feature_count=event.feature_count,
        duration_ms=event.duration_ms,
        feature_profile=tuple(
            FeatureRequestProfileResponse(
                feature_index=feature.feature_index,
                summary=_numeric(feature.summary),
                reference_bin_counts=feature.reference_bin_counts,
                out_of_reference_range_count=(feature.out_of_reference_range_count),
            )
            for feature in event.feature_profile
        ),
        prediction_profile=prediction_response,
        error_code=event.error_code,
        safe_error_message=event.safe_error_message,
        correlation_id=event.correlation_id,
        created_at=event.created_at,
        completed_at=event.completed_at,
    )


def _operations_response(
    summary: PredictionOperationalSummary,
) -> PredictionOperationalSummaryResponse:
    return PredictionOperationalSummaryResponse(
        registered_model_name=summary.registered_model_name,
        model_version=summary.model_version,
        start_at=summary.start_at,
        end_at=summary.end_at,
        request_count=summary.request_count,
        success_count=summary.success_count,
        failure_count=summary.failure_count,
        success_rate=summary.success_rate,
        failure_rate=summary.failure_rate,
        average_latency_ms=summary.average_latency_ms,
        minimum_latency_ms=summary.minimum_latency_ms,
        maximum_latency_ms=summary.maximum_latency_ms,
        p50_latency_ms=summary.p50_latency_ms,
        p95_latency_ms=summary.p95_latency_ms,
        p99_latency_ms=summary.p99_latency_ms,
        total_predicted_rows=summary.total_predicted_rows,
        average_batch_size=summary.average_batch_size,
        failures_by_error_code=dict(summary.failures_by_error_code),
        matched_event_count=summary.matched_event_count,
        analyzed_event_count=summary.analyzed_event_count,
        truncated=summary.truncated,
        analysis_warning=summary.analysis_warning,
        instance_capture_failures_since_start=(
            summary.instance_capture_failures_since_start
        ),
    )


def _data_quality_response(
    report: PredictionDataQualityReport,
) -> PredictionDataQualityResponse:
    return PredictionDataQualityResponse(
        registered_model_name=report.registered_model_name,
        model_version=report.model_version,
        start_at=report.start_at,
        end_at=report.end_at,
        request_count=report.request_count,
        row_count=report.row_count,
        missing_value_count=report.missing_value_count,
        non_finite_value_count=report.non_finite_value_count,
        feature_count_mismatch_requests=report.feature_count_mismatch_requests,
        empty_batch_requests=report.empty_batch_requests,
        constant_column_occurrences=report.constant_column_occurrences,
        out_of_reference_range_count=report.out_of_reference_range_count,
        finite_value_count=report.finite_value_count,
        out_of_reference_range_proportion=(report.out_of_reference_range_proportion),
        issues=tuple(
            DataQualityIssueResponse(
                code=issue.code,
                severity=issue.severity,
                count=issue.count,
                proportion=issue.proportion,
            )
            for issue in report.issues
        ),
        matched_event_count=report.matched_event_count,
        analyzed_event_count=report.analyzed_event_count,
        truncated=report.truncated,
        analysis_warning=report.analysis_warning,
    )


def _numeric_reference(
    profile: NumericReferenceProfile,
) -> NumericReferenceProfileResponse:
    return NumericReferenceProfileResponse(
        summary=_numeric(profile.summary),
        bin_edges=profile.bin_edges,
        bin_counts=profile.bin_counts,
    )


def _reference_response(
    profile: ModelReferenceProfile,
) -> ModelReferenceProfileResponse:
    prediction: (
        RegressionPredictionReferenceResponse
        | ClassificationPredictionReferenceResponse
    )
    if isinstance(profile.prediction, RegressionPredictionReferenceProfile):
        prediction = RegressionPredictionReferenceResponse(
            profile=_numeric_reference(profile.prediction.profile),
        )
    elif isinstance(
        profile.prediction,
        ClassificationPredictionReferenceProfile,
    ):
        classification = profile.prediction.profile
        prediction = ClassificationPredictionReferenceResponse(
            profile=ClassificationPredictionProfileResponse(
                count=classification.count,
                class_counts=dict(classification.class_counts),
                other_count=classification.other_count,
            ),
        )
    else:
        raise AssertionError("Unsupported prediction reference profile.")
    return ModelReferenceProfileResponse(
        profile_id=profile.id,
        registered_model_name=profile.registered_model_name,
        model_version=profile.model_version,
        trainer_key=_trainer_key(profile.key),
        source=profile.source,
        feature_count=profile.feature_count,
        features=tuple(
            FeatureReferenceProfileResponse(
                feature_index=feature.feature_index,
                profile=_numeric_reference(feature.profile),
            )
            for feature in profile.features
        ),
        prediction=prediction,
        sample_count=profile.sample_count,
        training_job_id=profile.training_job_id,
        created_at=profile.created_at,
    )


def _drift_response(report: ModelDriftReport) -> ModelDriftResponse:
    prediction = report.prediction_result
    prediction_response: (
        RegressionPredictionDriftResponse | ClassificationPredictionDriftResponse
    )
    if isinstance(prediction, RegressionPredictionDrift):
        prediction_response = RegressionPredictionDriftResponse(
            psi=prediction.psi,
            mean_shift=prediction.mean_shift,
            standard_deviation_ratio=prediction.standard_deviation_ratio,
            reference_sample_count=prediction.reference_sample_count,
            current_sample_count=prediction.current_sample_count,
            severity=prediction.severity,
        )
    elif isinstance(prediction, ClassificationPredictionDrift):
        prediction_response = ClassificationPredictionDriftResponse(
            total_variation_distance=prediction.total_variation_distance,
            reference_sample_count=prediction.reference_sample_count,
            current_sample_count=prediction.current_sample_count,
            severity=prediction.severity,
        )
    else:
        raise AssertionError("Unsupported prediction drift result.")
    return ModelDriftResponse(
        registered_model_name=report.registered_model_name,
        model_version=report.model_version,
        trainer_key=_trainer_key(report.key),
        reference_profile_source=report.reference_source,
        reference_sample_count=report.reference_sample_count,
        current_sample_count=report.current_sample_count,
        start_at=report.start_at,
        end_at=report.end_at,
        feature_results=tuple(
            FeatureDriftResponse(
                feature_index=feature.feature_index,
                psi=feature.psi,
                reference_sample_count=feature.reference_sample_count,
                current_sample_count=feature.current_sample_count,
                missing_rate_difference=feature.missing_rate_difference,
                out_of_reference_range_proportion=(
                    feature.out_of_reference_range_proportion
                ),
                severity=feature.severity,
            )
            for feature in report.feature_results
        ),
        prediction_result=prediction_response,
        aggregate_status=report.aggregate_status,
        thresholds=DriftThresholdsResponse(
            warning=report.thresholds.warning,
            critical=report.thresholds.critical,
            missing_rate_warning=report.thresholds.missing_rate_warning,
            out_of_range_warning=report.thresholds.out_of_range_warning,
            epsilon=report.thresholds.epsilon,
        ),
        generated_at=report.generated_at,
        matched_event_count=report.matched_event_count,
        analyzed_event_count=report.analyzed_event_count,
        truncated=report.truncated,
        analysis_warning=report.analysis_warning,
    )
