"""Application orchestration over monitoring, persistence, and existing jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.ml.jobs import TrainingJobRecord
from app.ml.jobs.exceptions import TrainingJobError
from app.ml.jobs.service import TrainingJobService
from app.ml.monitoring import (
    DataQualitySeverity,
    DriftSeverity,
    ModelDriftReport,
    MonitoringNotFoundError,
    PredictionDataQualityReport,
    PredictionMonitoringError,
)
from app.ml.monitoring.evaluation_models import (
    ModelMonitoringEvaluation,
    MonitoringEvaluationStatus,
)
from app.ml.monitoring.service import PredictionMonitoringService
from app.ml.registry import BaseModelRegistry, RegisteredModelVersion
from app.ml.registry.exceptions import ModelRegistryError
from app.ml.retraining.exceptions import (
    RetrainingDependencyError,
    RetrainingNotFoundError,
    RetrainingPersistenceError,
    RetrainingRegistryError,
    RetrainingValidationError,
)
from app.ml.retraining.models import (
    CooldownState,
    QuotaState,
    RetrainingDecision,
    RetrainingEvaluationMode,
    RetrainingPolicy,
    RetrainingRequest,
    RetrainingRequestStatus,
    RetrainingTrigger,
    RetrainingTriggerType,
    retraining_idempotency_key,
)
from app.ml.retraining.policy import (
    RetrainingEvaluationContext,
    RetrainingPolicyEvaluator,
)
from app.ml.retraining.specification import build_retraining_specification
from app.observability.logging import emit_safe
from app.observability.metrics import record_retraining_decision
from app.repositories.ai_retraining import (
    RetrainingAuditPage,
    RetrainingRepository,
    RetrainingRequestPage,
)
from app.utils.security import utc_now

type Clock = Callable[[], datetime]
type IdFactory = Callable[[], UUID]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetrainingEvaluationResult:
    """Transport-neutral decision and its optional durable execution request."""

    decision: RetrainingDecision
    request: RetrainingRequest | None


@dataclass(frozen=True, slots=True)
class PolicyDefaults:
    """Conservative application defaults overridden by persisted policy fields."""

    cooldown_seconds: int
    maximum_requests_per_day: int
    maximum_requests_per_week: int
    maximum_active_requests: int
    minimum_drift_status: DriftSeverity
    allow_truncated_drift: bool


class RetrainingService:
    """Coordinate explicit evaluation while reusing the existing training actor."""

    def __init__(
        self,
        *,
        repository: RetrainingRepository,
        monitoring_service: PredictionMonitoringService,
        model_registry: BaseModelRegistry,
        training_job_service: TrainingJobService,
        evaluator: RetrainingPolicyEvaluator,
        defaults: PolicyDefaults,
        clock: Clock = utc_now,
        id_factory: IdFactory = uuid4,
    ) -> None:
        self._repository = repository
        self._monitoring = monitoring_service
        self._registry = model_registry
        self._jobs = training_job_service
        self._evaluator = evaluator
        self._defaults = defaults
        self._clock = clock
        self._id_factory = id_factory

    async def put_policy(
        self,
        *,
        registered_model_name: str,
        created_by_user_id: UUID,
        enabled: bool,
        allowed_trigger_types: frozenset[RetrainingTriggerType],
        minimum_drift_status: DriftSeverity | None,
        minimum_current_sample_count: int,
        cooldown_seconds: int | None,
        maximum_requests_per_day: int | None,
        maximum_requests_per_week: int | None,
        maximum_active_requests: int | None,
        require_champion_source: bool,
        allow_truncated_drift: bool | None,
    ) -> RetrainingPolicy:
        """Create or replace the current model policy with validated values."""
        now = self._clock()
        existing = await self._safe_policy(registered_model_name)
        try:
            policy = RetrainingPolicy(
                id=existing.id if existing else self._id_factory(),
                registered_model_name=registered_model_name,
                enabled=enabled,
                allowed_trigger_types=allowed_trigger_types,
                minimum_drift_status=(
                    minimum_drift_status or self._defaults.minimum_drift_status
                ),
                minimum_current_sample_count=minimum_current_sample_count,
                cooldown_seconds=(
                    self._defaults.cooldown_seconds
                    if cooldown_seconds is None
                    else cooldown_seconds
                ),
                maximum_requests_per_day=(
                    self._defaults.maximum_requests_per_day
                    if maximum_requests_per_day is None
                    else maximum_requests_per_day
                ),
                maximum_requests_per_week=(
                    self._defaults.maximum_requests_per_week
                    if maximum_requests_per_week is None
                    else maximum_requests_per_week
                ),
                maximum_active_requests=(
                    self._defaults.maximum_active_requests
                    if maximum_active_requests is None
                    else maximum_active_requests
                ),
                require_champion_source=require_champion_source,
                allow_truncated_drift=(
                    self._defaults.allow_truncated_drift
                    if allow_truncated_drift is None
                    else allow_truncated_drift
                ),
                created_by_user_id=(
                    existing.created_by_user_id if existing else created_by_user_id
                ),
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            saved = await self._repository.upsert_policy(policy)
            await self._repository.commit()
            return saved
        except ValueError as exc:
            await self._repository.rollback()
            raise RetrainingValidationError(str(exc)) from exc
        except SQLAlchemyError as exc:
            await self._repository.rollback()
            raise RetrainingPersistenceError(
                "Retraining policy storage is unavailable."
            ) from exc

    async def get_policy(self, registered_model_name: str) -> RetrainingPolicy:
        policy = await self._safe_policy(registered_model_name)
        if policy is None:
            raise RetrainingNotFoundError("Retraining policy not found.")
        return policy

    async def list_policies(
        self, *, limit: int, offset: int
    ) -> tuple[RetrainingPolicy, ...]:
        try:
            return await self._repository.list_policies(limit=limit, offset=offset)
        except SQLAlchemyError as exc:
            raise RetrainingPersistenceError(
                "Retraining policy storage is unavailable."
            ) from exc

    async def evaluate_automatic(
        self,
        *,
        registered_model_name: str,
        version_or_alias: str,
        trigger_type: RetrainingTriggerType,
        start_at: datetime | None,
        end_at: datetime | None,
        minimum_sample_count: int | None,
        submit_if_eligible: bool,
        requested_by_user_id: UUID,
    ) -> RetrainingEvaluationResult:
        """Evaluate a requested monitoring window; never runs during prediction."""
        if trigger_type is RetrainingTriggerType.MANUAL:
            raise RetrainingValidationError(
                "Manual triggers must use the manual retraining endpoint."
            )
        policy = await self.get_policy(registered_model_name)
        version = self._resolve(registered_model_name, version_or_alias)
        report: ModelDriftReport | None = None
        quality_report: PredictionDataQualityReport | None = None
        try:
            if trigger_type is RetrainingTriggerType.DATA_QUALITY:
                quality_report = await self._monitoring.data_quality(
                    registered_model_name=registered_model_name,
                    version_or_alias=version.version,
                    start_at=start_at,
                    end_at=end_at,
                )
            else:
                report = await self._monitoring.drift(
                    registered_model_name=registered_model_name,
                    version_or_alias=version.version,
                    start_at=start_at,
                    end_at=end_at,
                    minimum_sample_count=minimum_sample_count,
                )
        except MonitoringNotFoundError:
            pass
        except PredictionMonitoringError as exc:
            raise RetrainingDependencyError(
                "Prediction monitoring could not evaluate retraining safely."
            ) from exc
        trigger = (
            _data_quality_trigger(quality_report)
            if quality_report is not None
            else _automatic_trigger(
                trigger_type=trigger_type,
                version=version,
                report=report,
                start_at=start_at,
                end_at=end_at,
            )
        )
        return await self._evaluate(
            policy=policy,
            version=version,
            requested_alias=(
                version_or_alias if not version_or_alias.isdigit() else None
            ),
            trigger=trigger,
            mode=RetrainingEvaluationMode.AUTOMATIC,
            submit_if_eligible=submit_if_eligible,
            requested_by_user_id=requested_by_user_id,
            reason=None,
            override_cooldown=False,
            override_reason=None,
            reference_profile_available=(
                report is not None or quality_report is not None
            ),
        )

    async def request_manual(
        self,
        *,
        registered_model_name: str,
        version_or_alias: str,
        reason: str,
        requested_by_user_id: UUID,
        override_cooldown: bool,
        requester_is_admin: bool,
    ) -> RetrainingEvaluationResult:
        """Submit a named human request with the same evidence and job boundary."""
        normalized_reason = reason.strip()
        if not normalized_reason or len(normalized_reason) > 1000:
            raise RetrainingValidationError(
                "Manual retraining reason must be between 1 and 1000 characters."
            )
        if override_cooldown and not requester_is_admin:
            raise RetrainingValidationError(
                "Only an administrator may override retraining cooldown."
            )
        policy = await self.get_policy(registered_model_name)
        version = self._resolve(registered_model_name, version_or_alias)
        reference = (
            "manual:"
            + sha256(f"{requested_by_user_id}:{normalized_reason}".encode()).hexdigest()
        )
        trigger = RetrainingTrigger(
            trigger_type=RetrainingTriggerType.MANUAL,
            reference=reference,
            aggregate_status=None,
            matched_event_count=0,
            analyzed_event_count=0,
            current_sample_count=0,
            truncated=False,
            analysis_warning=None,
            thresholds={},
        )
        return await self._evaluate(
            policy=policy,
            version=version,
            requested_alias=(
                version_or_alias if not version_or_alias.isdigit() else None
            ),
            trigger=trigger,
            mode=RetrainingEvaluationMode.MANUAL,
            submit_if_eligible=True,
            requested_by_user_id=requested_by_user_id,
            reason=normalized_reason,
            override_cooldown=override_cooldown,
            override_reason=normalized_reason if override_cooldown else None,
            reference_profile_available=True,
        )

    async def evaluate_monitoring_evaluation(
        self,
        *,
        evaluation: ModelMonitoringEvaluation,
        trigger_type: RetrainingTriggerType,
        submit_if_eligible: bool,
        requested_by_user_id: UUID,
    ) -> RetrainingEvaluationResult:
        """Apply existing governance to one immutable persisted evaluation."""
        if trigger_type is RetrainingTriggerType.MANUAL:
            raise RetrainingValidationError(
                "Persisted monitoring evaluations cannot use a manual trigger."
            )
        policy = await self.get_policy(evaluation.registered_model_name)
        version = self._resolve(
            evaluation.registered_model_name, evaluation.model_version
        )
        if version.version != evaluation.model_version or version.key != evaluation.key:
            raise RetrainingValidationError(
                "Monitoring evaluation identity does not match the registered version."
            )
        trigger = _persisted_evaluation_trigger(evaluation, trigger_type)
        return await self._evaluate(
            policy=policy,
            version=version,
            requested_alias=evaluation.model_alias,
            trigger=trigger,
            mode=RetrainingEvaluationMode.AUTOMATIC,
            submit_if_eligible=submit_if_eligible,
            requested_by_user_id=requested_by_user_id,
            reason=None,
            override_cooldown=False,
            override_reason=None,
            reference_profile_available=(
                evaluation.overall_status is not MonitoringEvaluationStatus.UNAVAILABLE
            ),
            monitoring_evaluation_id=evaluation.id,
        )

    async def _evaluate(
        self,
        *,
        policy: RetrainingPolicy,
        version: RegisteredModelVersion,
        requested_alias: str | None,
        trigger: RetrainingTrigger,
        mode: RetrainingEvaluationMode,
        submit_if_eligible: bool,
        requested_by_user_id: UUID,
        reason: str | None,
        override_cooldown: bool,
        override_reason: str | None,
        reference_profile_available: bool,
        monitoring_evaluation_id: UUID | None = None,
    ) -> RetrainingEvaluationResult:
        now = self._clock()
        source_job = await self._safe_source_job(
            version.registered_model_name, version.version
        )
        key = retraining_idempotency_key(
            registered_model_name=version.registered_model_name,
            source_model_version=version.version,
            trigger=trigger,
            policy_version=policy.version_token,
        )
        try:
            duplicate = await self._repository.get_by_idempotency(key)
            active = await self._repository.active_request(
                version.registered_model_name
            )
            counts = await self._repository.request_counts(
                registered_model_name=version.registered_model_name,
                day_start=now.astimezone(UTC).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ),
                week_start=_week_start(now),
            )
        except SQLAlchemyError as exc:
            raise RetrainingPersistenceError(
                "Retraining request storage is unavailable."
            ) from exc
        cooldown, quota = _states(policy=policy, counts=counts, now=now)
        champion = self._resolve_optional(version.registered_model_name, "champion")
        context = RetrainingEvaluationContext(
            policy=policy,
            registered_model_name=version.registered_model_name,
            source_model_version=version.version,
            requested_alias=requested_alias,
            trigger=trigger,
            mode=mode,
            source_is_champion=(
                champion is not None and champion.version == version.version
            ),
            reference_profile_available=reference_profile_available,
            training_evidence_available=(
                source_job is not None and source_job.key == version.key
            ),
            existing_equivalent_request_id=duplicate.id if duplicate else None,
            active_request_id=(
                active.id
                if active is not None and counts[2] >= policy.maximum_active_requests
                else None
            ),
            cooldown=cooldown,
            quota=quota,
            evaluated_at=now,
            override_cooldown=override_cooldown,
        )
        decision = self._evaluator.evaluate(context)
        request: RetrainingRequest | None = duplicate
        if decision.eligible and submit_if_eligible and source_job is not None:
            request = await self._persist_request(
                decision=decision,
                policy=policy,
                source_job=source_job,
                requested_by_user_id=requested_by_user_id,
                mode=mode,
                idempotency_key=key,
                reason=reason,
                override_used=override_cooldown,
                monitoring_evaluation_id=monitoring_evaluation_id,
            )
        try:
            await self._repository.create_audit(
                decision=decision,
                policy_id=policy.id,
                evaluated_by_user_id=requested_by_user_id,
                mode=mode,
                override_used=override_cooldown,
                override_reason=override_reason,
                created_request_id=(
                    request.id if request is not None and decision.eligible else None
                ),
                monitoring_evaluation_id=monitoring_evaluation_id,
            )
            await self._repository.commit()
        except SQLAlchemyError as exc:
            await self._repository.rollback()
            raise RetrainingPersistenceError(
                "Retraining audit storage is unavailable."
            ) from exc
        record_retraining_decision(
            trigger=trigger.trigger_type.value,
            final_status=decision.status.value,
            request_created=(
                decision.eligible
                and submit_if_eligible
                and duplicate is None
                and request is not None
            ),
        )
        emit_safe(
            logger,
            logging.INFO,
            "retraining_decision_outcome",
            extra={
                "job_name": "retraining_reconciliation",
                "trigger": trigger.trigger_type.value,
                "lifecycle_status": decision.status.value,
            },
        )
        if (
            request is not None
            and request.training_job_id is None
            and decision.eligible
        ):
            request = await self.resume_submission(request, source_job)
        return RetrainingEvaluationResult(decision, request)

    async def _persist_request(
        self,
        *,
        decision: RetrainingDecision,
        policy: RetrainingPolicy,
        source_job: TrainingJobRecord,
        requested_by_user_id: UUID,
        mode: RetrainingEvaluationMode,
        idempotency_key: str,
        reason: str | None,
        override_used: bool,
        monitoring_evaluation_id: UUID | None,
    ) -> RetrainingRequest:
        now = self._clock()
        request = RetrainingRequest(
            id=self._id_factory(),
            registered_model_name=decision.registered_model_name,
            source_model_version=decision.source_model_version or "",
            source_training_job_id=source_job.id,
            key=source_job.key,
            trigger_type=decision.trigger.trigger_type,
            trigger_reference=decision.trigger.reference,
            policy_id=policy.id,
            decision_status=decision.status,
            request_status=RetrainingRequestStatus.PENDING,
            evaluation_mode=mode,
            idempotency_key=idempotency_key,
            training_job_id=None,
            resulting_model_version=None,
            requested_by_user_id=requested_by_user_id,
            reason=reason,
            override_used=override_used,
            requested_at=now,
            started_at=None,
            completed_at=None,
            safe_failure_code=None,
            safe_failure_message=None,
            comparison=None,
            created_at=now,
            updated_at=now,
            monitoring_evaluation_id=monitoring_evaluation_id,
        )
        try:
            return await self._repository.create_request(request)
        except IntegrityError:
            await self._repository.rollback()
            existing = await self._repository.get_by_idempotency(idempotency_key)
            if existing is None:
                raise RetrainingPersistenceError(
                    "Retraining request could not be persisted safely."
                ) from None
            return existing

    async def resume_submission(
        self,
        request: RetrainingRequest,
        source_job: TrainingJobRecord | None,
    ) -> RetrainingRequest:
        """Resume the post-request durable checkpoint without duplicating a job."""
        if source_job is None:
            source_job = await self._safe_source_job(
                request.registered_model_name, request.source_model_version
            )
        if source_job is None:
            return request
        specification = build_retraining_specification(
            source=source_job.specification,
            request_id=request.id,
            trigger_type=request.trigger_type,
            source_model_version=request.source_model_version,
            source_training_job_id=source_job.id,
            policy_id=request.policy_id,
        )
        try:
            submission = await self._jobs.submit(
                requested_by_user_id=request.requested_by_user_id,
                key=request.key,
                specification=specification,
                idempotency_key="retraining-" + request.idempotency_key,
            )
            attached = await self._repository.attach_training_job(
                request_id=request.id,
                training_job_id=submission.job.id,
                updated_at=self._clock(),
            )
            await self._repository.commit()
            return attached or (await self.get_request(request.id))
        except (TrainingJobError, SQLAlchemyError) as exc:
            await self._repository.rollback()
            await self._repository.update_execution(
                request_id=request.id,
                status=RetrainingRequestStatus.PENDING,
                updated_at=self._clock(),
                failure_code="training_submission_pending",
                failure_message=(
                    "Background training submission requires reconciliation."
                ),
            )
            await self._repository.commit()
            raise RetrainingDependencyError(
                "Background retraining submission requires reconciliation."
            ) from exc

    async def get_request(self, request_id: UUID) -> RetrainingRequest:
        try:
            request = await self._repository.get_request(request_id)
        except SQLAlchemyError as exc:
            raise RetrainingPersistenceError(
                "Retraining request storage is unavailable."
            ) from exc
        if request is None:
            raise RetrainingNotFoundError("Retraining request not found.")
        return request

    async def list_requests(
        self, *, registered_model_name: str | None, limit: int, offset: int
    ) -> RetrainingRequestPage:
        try:
            return await self._repository.list_requests(
                registered_model_name=registered_model_name,
                limit=limit,
                offset=offset,
            )
        except SQLAlchemyError as exc:
            raise RetrainingPersistenceError(
                "Retraining request storage is unavailable."
            ) from exc

    async def aggregate_status(self) -> tuple[int, int, int, int]:
        """Return operator-safe aggregate counts without lineage details."""
        try:
            return await self._repository.aggregate_status()
        except SQLAlchemyError as exc:
            raise RetrainingPersistenceError(
                "Retraining request storage is unavailable."
            ) from exc

    async def list_audits(self, *, limit: int, offset: int) -> RetrainingAuditPage:
        try:
            return await self._repository.list_audits(limit=limit, offset=offset)
        except SQLAlchemyError as exc:
            raise RetrainingPersistenceError(
                "Retraining audit storage is unavailable."
            ) from exc

    async def _safe_policy(self, name: str) -> RetrainingPolicy | None:
        try:
            return await self._repository.get_policy(name)
        except SQLAlchemyError as exc:
            raise RetrainingPersistenceError(
                "Retraining policy storage is unavailable."
            ) from exc

    async def _safe_source_job(
        self, name: str, version: str
    ) -> TrainingJobRecord | None:
        try:
            return await self._repository.find_source_training_job(
                registered_model_name=name, model_version=version
            )
        except SQLAlchemyError as exc:
            raise RetrainingPersistenceError(
                "Source training evidence storage is unavailable."
            ) from exc

    def _resolve(self, name: str, version_or_alias: str) -> RegisteredModelVersion:
        try:
            return self._registry.resolve(name, version_or_alias)
        except ModelRegistryError as exc:
            raise RetrainingRegistryError(
                "The registered model version could not be resolved."
            ) from exc

    def _resolve_optional(self, name: str, alias: str) -> RegisteredModelVersion | None:
        try:
            return self._registry.resolve(name, alias)
        except ModelRegistryError:
            return None


def _automatic_trigger(
    *,
    trigger_type: RetrainingTriggerType,
    version: RegisteredModelVersion,
    report: ModelDriftReport | None,
    start_at: datetime | None,
    end_at: datetime | None,
) -> RetrainingTrigger:
    if report is None:
        reference = (
            "window:"
            + sha256(f"{version.version}:{start_at}:{end_at}".encode()).hexdigest()
        )
        return RetrainingTrigger(
            trigger_type, reference, None, 0, 0, 0, False, None, {}
        )
    reference = (
        f"window:{report.model_version}:{report.start_at.isoformat()}:"
        f"{report.end_at.isoformat()}"
    )
    thresholds = {
        "psi_warning": report.thresholds.warning,
        "psi_critical": report.thresholds.critical,
        "missing_rate_warning": report.thresholds.missing_rate_warning,
        "out_of_range_warning": report.thresholds.out_of_range_warning,
    }
    aggregate_status = report.aggregate_status
    if trigger_type is RetrainingTriggerType.FEATURE_DRIFT:
        aggregate_status = _maximum_severity(
            tuple(item.severity for item in report.feature_results)
        )
    elif trigger_type is RetrainingTriggerType.PREDICTION_DRIFT:
        aggregate_status = report.prediction_result.severity
    return RetrainingTrigger(
        trigger_type=trigger_type,
        reference=reference,
        aggregate_status=aggregate_status,
        matched_event_count=report.matched_event_count,
        analyzed_event_count=report.analyzed_event_count,
        current_sample_count=report.current_sample_count,
        truncated=report.truncated,
        analysis_warning=report.analysis_warning,
        thresholds=thresholds,
    )


def _data_quality_trigger(report: PredictionDataQualityReport) -> RetrainingTrigger:
    severities = {item.severity for item in report.issues}
    if DataQualitySeverity.CRITICAL in severities:
        aggregate = DriftSeverity.CRITICAL
    elif DataQualitySeverity.WARNING in severities:
        aggregate = DriftSeverity.WARNING
    else:
        aggregate = DriftSeverity.STABLE
    reference = (
        f"quality:{report.model_version}:{report.start_at.isoformat()}:"
        f"{report.end_at.isoformat()}"
    )
    return RetrainingTrigger(
        trigger_type=RetrainingTriggerType.DATA_QUALITY,
        reference=reference,
        aggregate_status=aggregate,
        matched_event_count=report.matched_event_count,
        analyzed_event_count=report.analyzed_event_count,
        current_sample_count=report.analyzed_event_count,
        truncated=report.truncated,
        analysis_warning=report.analysis_warning,
        thresholds={},
    )


def _persisted_evaluation_trigger(
    evaluation: ModelMonitoringEvaluation,
    trigger_type: RetrainingTriggerType,
) -> RetrainingTrigger:
    statuses = {
        RetrainingTriggerType.FEATURE_DRIFT: evaluation.feature_drift_status,
        RetrainingTriggerType.PREDICTION_DRIFT: evaluation.prediction_drift_status,
        RetrainingTriggerType.DATA_QUALITY: evaluation.data_quality_status,
    }
    status = statuses[trigger_type]
    severity = {
        MonitoringEvaluationStatus.HEALTHY: DriftSeverity.STABLE,
        MonitoringEvaluationStatus.WARNING: DriftSeverity.WARNING,
        MonitoringEvaluationStatus.CRITICAL: DriftSeverity.CRITICAL,
        MonitoringEvaluationStatus.INSUFFICIENT_DATA: (DriftSeverity.INSUFFICIENT_DATA),
        MonitoringEvaluationStatus.UNAVAILABLE: DriftSeverity.INSUFFICIENT_DATA,
    }[status]
    drift = evaluation.report.get("drift")
    drift_payload = drift if isinstance(drift, dict) else {}
    raw_thresholds = drift_payload.get("thresholds")
    thresholds = (
        {
            str(key): float(value)
            for key, value in raw_thresholds.items()
            if isinstance(key, str)
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        }
        if isinstance(raw_thresholds, dict)
        else {}
    )
    matched = (
        evaluation.successful_prediction_count + evaluation.failed_prediction_count
    )
    analyzed = drift_payload.get("analyzed_event_count", matched)
    return RetrainingTrigger(
        trigger_type=trigger_type,
        reference=f"evaluation:{evaluation.id}",
        aggregate_status=severity,
        matched_event_count=matched,
        analyzed_event_count=(analyzed if isinstance(analyzed, int) else matched),
        current_sample_count=evaluation.evaluated_sample_count,
        truncated=bool(drift_payload.get("truncated", False)),
        analysis_warning=(
            str(drift_payload["analysis_warning"])
            if drift_payload.get("analysis_warning")
            else None
        ),
        thresholds=thresholds,
    )


def _maximum_severity(values: tuple[DriftSeverity, ...]) -> DriftSeverity:
    order = {
        DriftSeverity.INSUFFICIENT_DATA: 0,
        DriftSeverity.STABLE: 1,
        DriftSeverity.WARNING: 2,
        DriftSeverity.CRITICAL: 3,
    }
    if not values:
        return DriftSeverity.INSUFFICIENT_DATA
    return max(values, key=order.__getitem__)


def _states(
    *,
    policy: RetrainingPolicy,
    counts: tuple[int, int, int, datetime | None],
    now: datetime,
) -> tuple[CooldownState, QuotaState]:
    day, week, active, last = counts
    expires = last + timedelta(seconds=policy.cooldown_seconds) if last else None
    cooldown_active = expires is not None and now < expires
    remaining = (
        int((expires - now).total_seconds())
        if cooldown_active and expires is not None
        else 0
    )
    return (
        CooldownState(cooldown_active, last, expires, max(0, remaining)),
        QuotaState(
            day,
            week,
            active,
            policy.maximum_requests_per_day,
            policy.maximum_requests_per_week,
            policy.maximum_active_requests,
        ),
    )


def _week_start(now: datetime) -> datetime:
    today = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=today.weekday())
