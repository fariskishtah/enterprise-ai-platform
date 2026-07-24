"""SQL persistence boundary for retraining policy, requests, and audits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.ml.base import TrainerKey
from app.ml.jobs import TrainingJobRecord, TrainingJobStatus
from app.ml.monitoring import DriftSeverity
from app.ml.retraining.models import (
    CandidateComparison,
    ComparisonStatus,
    CooldownState,
    MetricComparison,
    QuotaState,
    RetrainingAuditRecord,
    RetrainingDecision,
    RetrainingEvaluationMode,
    RetrainingPolicy,
    RetrainingRequest,
    RetrainingRequestStatus,
    RetrainingTrigger,
    RetrainingTriggerType,
)
from app.models.ai_governance import TrainingJob
from app.models.ai_retraining import (
    ModelRetrainingAudit,
    ModelRetrainingPolicy,
    ModelRetrainingRequest,
)
from app.models.user import AuditEvent
from app.repositories.ai_governance import _job_record
from app.repositories.tenant import company_for_user

_ACTIVE_STATUSES = (
    RetrainingRequestStatus.PENDING,
    RetrainingRequestStatus.SUBMITTED,
    RetrainingRequestStatus.TRAINING,
    RetrainingRequestStatus.CANDIDATE_CREATED,
)


@dataclass(frozen=True, slots=True)
class RetrainingRequestPage:
    items: tuple[RetrainingRequest, ...]
    total: int


@dataclass(frozen=True, slots=True)
class RetrainingAuditPage:
    items: tuple[RetrainingAuditRecord, ...]
    total: int


class RetrainingRepository:
    """Own all persisted counters and conditional retraining checkpoints."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_terminal_audit(
        self,
        *,
        request: RetrainingRequest,
        job: TrainingJobRecord,
        status: RetrainingRequestStatus,
    ) -> None:
        """Stage a safe unified event beside a terminal reconciliation."""
        succeeded = status is RetrainingRequestStatus.COMPLETED
        self._session.add(
            AuditEvent(
                company_id=job.company_id,
                actor_user_id=request.requested_by_user_id,
                actor_role=None,
                action=("retraining.completed" if succeeded else "retraining.failed"),
                resource_type="retraining_request",
                resource_id=str(request.id),
                result="success" if succeeded else "failure",
                safe_metadata={
                    "status": status.value,
                    "training_job_id": str(job.id),
                    "error_code": job.error_code,
                },
                retention_class="operations",
            )
        )

    async def get_policy(self, registered_model_name: str) -> RetrainingPolicy | None:
        entity = (
            await self._session.execute(
                select(ModelRetrainingPolicy).where(
                    ModelRetrainingPolicy.registered_model_name == registered_model_name
                )
            )
        ).scalar_one_or_none()
        return _policy(entity) if entity is not None else None

    async def list_policies(
        self, *, limit: int, offset: int
    ) -> tuple[RetrainingPolicy, ...]:
        result = await self._session.execute(
            select(ModelRetrainingPolicy)
            .order_by(ModelRetrainingPolicy.registered_model_name)
            .limit(limit)
            .offset(offset)
        )
        return tuple(_policy(item) for item in result.scalars())

    async def upsert_policy(self, policy: RetrainingPolicy) -> RetrainingPolicy:
        entity = (
            await self._session.execute(
                select(ModelRetrainingPolicy).where(
                    ModelRetrainingPolicy.registered_model_name
                    == policy.registered_model_name
                )
            )
        ).scalar_one_or_none()
        values = {
            "enabled": policy.enabled,
            "allowed_trigger_types": sorted(
                item.value for item in policy.allowed_trigger_types
            ),
            "minimum_drift_status": policy.minimum_drift_status,
            "minimum_current_sample_count": policy.minimum_current_sample_count,
            "cooldown_seconds": policy.cooldown_seconds,
            "maximum_requests_per_day": policy.maximum_requests_per_day,
            "maximum_requests_per_week": policy.maximum_requests_per_week,
            "maximum_active_requests": policy.maximum_active_requests,
            "require_champion_source": policy.require_champion_source,
            "allow_truncated_drift": policy.allow_truncated_drift,
            "updated_at": policy.updated_at,
        }
        if entity is None:
            entity = ModelRetrainingPolicy(
                id=policy.id,
                company_id=await company_for_user(
                    self._session, policy.created_by_user_id
                ),
                registered_model_name=policy.registered_model_name,
                created_by_user_id=policy.created_by_user_id,
                created_at=policy.created_at,
                **values,
            )
            self._session.add(entity)
        else:
            for name, value in values.items():
                setattr(entity, name, value)
        await self._session.flush()
        await self._session.refresh(entity)
        return _policy(entity)

    async def find_source_training_job(
        self, *, registered_model_name: str, model_version: str
    ) -> TrainingJobRecord | None:
        entity = (
            await self._session.execute(
                select(TrainingJob).where(
                    TrainingJob.registered_model_name == registered_model_name,
                    TrainingJob.registered_model_version == model_version,
                    TrainingJob.status == TrainingJobStatus.SUCCEEDED,
                )
            )
        ).scalar_one_or_none()
        return _job_record(entity) if entity is not None else None

    async def get_request(self, request_id: UUID) -> RetrainingRequest | None:
        entity = await self._session.get(ModelRetrainingRequest, request_id)
        return _request(entity) if entity is not None else None

    async def get_training_job(self, job_id: UUID) -> TrainingJobRecord | None:
        entity = await self._session.get(TrainingJob, job_id)
        return _job_record(entity) if entity is not None else None

    async def get_by_idempotency(self, key: str) -> RetrainingRequest | None:
        entity = (
            await self._session.execute(
                select(ModelRetrainingRequest).where(
                    ModelRetrainingRequest.idempotency_key == key
                )
            )
        ).scalar_one_or_none()
        return _request(entity) if entity is not None else None

    async def get_by_training_job(self, job_id: UUID) -> RetrainingRequest | None:
        entity = (
            await self._session.execute(
                select(ModelRetrainingRequest).where(
                    ModelRetrainingRequest.training_job_id == job_id
                )
            )
        ).scalar_one_or_none()
        return _request(entity) if entity is not None else None

    async def active_request(
        self, registered_model_name: str
    ) -> RetrainingRequest | None:
        entity = (
            await self._session.execute(
                select(ModelRetrainingRequest)
                .where(
                    ModelRetrainingRequest.registered_model_name
                    == registered_model_name,
                    ModelRetrainingRequest.request_status.in_(_ACTIVE_STATUSES),
                )
                .order_by(ModelRetrainingRequest.requested_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return _request(entity) if entity is not None else None

    async def request_counts(
        self,
        *,
        registered_model_name: str,
        day_start: datetime,
        week_start: datetime,
    ) -> tuple[int, int, int, datetime | None]:
        base = ModelRetrainingRequest.registered_model_name == registered_model_name
        automatic = (
            ModelRetrainingRequest.evaluation_mode == RetrainingEvaluationMode.AUTOMATIC
        )
        day = await self._count(
            base, automatic, ModelRetrainingRequest.requested_at >= day_start
        )
        week = await self._count(
            base, automatic, ModelRetrainingRequest.requested_at >= week_start
        )
        active = await self._count(
            base, ModelRetrainingRequest.request_status.in_(_ACTIVE_STATUSES)
        )
        last = (
            await self._session.execute(
                select(func.max(ModelRetrainingRequest.requested_at)).where(
                    base, automatic
                )
            )
        ).scalar_one()
        return day, week, active, _optional_aware(last)

    async def _count(self, *conditions: ColumnElement[bool]) -> int:
        value = (
            await self._session.execute(
                select(func.count())
                .select_from(ModelRetrainingRequest)
                .where(*conditions)
            )
        ).scalar_one()
        return int(value)

    async def create_request(self, request: RetrainingRequest) -> RetrainingRequest:
        entity = ModelRetrainingRequest(
            id=request.id,
            company_id=await company_for_user(
                self._session, request.requested_by_user_id
            ),
            registered_model_name=request.registered_model_name,
            source_model_version=request.source_model_version,
            source_training_job_id=request.source_training_job_id,
            algorithm=request.key.algorithm,
            task_type=request.key.task_type,
            trigger_type=request.trigger_type,
            trigger_reference=request.trigger_reference,
            policy_id=request.policy_id,
            decision_status=request.decision_status,
            request_status=request.request_status,
            evaluation_mode=request.evaluation_mode,
            idempotency_key=request.idempotency_key,
            training_job_id=request.training_job_id,
            monitoring_evaluation_id=request.monitoring_evaluation_id,
            resulting_model_version=request.resulting_model_version,
            requested_by_user_id=request.requested_by_user_id,
            reason=request.reason,
            override_used=request.override_used,
            requested_at=request.requested_at,
            started_at=request.started_at,
            completed_at=request.completed_at,
            safe_failure_code=request.safe_failure_code,
            safe_failure_message=request.safe_failure_message,
            comparison=_comparison_payload(request.comparison),
            created_at=request.created_at,
            updated_at=request.updated_at,
        )
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return _request(entity)

    async def attach_training_job(
        self, *, request_id: UUID, training_job_id: UUID, updated_at: datetime
    ) -> RetrainingRequest | None:
        entity = (
            await self._session.execute(
                update(ModelRetrainingRequest)
                .where(
                    ModelRetrainingRequest.id == request_id,
                    ModelRetrainingRequest.training_job_id.is_(None),
                    ModelRetrainingRequest.request_status
                    == RetrainingRequestStatus.PENDING,
                )
                .values(
                    training_job_id=training_job_id,
                    request_status=RetrainingRequestStatus.SUBMITTED,
                    updated_at=updated_at,
                )
                .returning(ModelRetrainingRequest)
            )
        ).scalar_one_or_none()
        return _request(entity) if entity is not None else None

    async def update_execution(
        self,
        *,
        request_id: UUID,
        status: RetrainingRequestStatus,
        updated_at: datetime,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        resulting_model_version: str | None = None,
        failure_code: str | None = None,
        failure_message: str | None = None,
        comparison: CandidateComparison | None = None,
    ) -> RetrainingRequest | None:
        values: dict[str, object] = {
            "request_status": status,
            "updated_at": updated_at,
            "safe_failure_code": failure_code,
            "safe_failure_message": failure_message,
        }
        if started_at is not None:
            values["started_at"] = started_at
        if completed_at is not None:
            values["completed_at"] = completed_at
        if resulting_model_version is not None:
            values["resulting_model_version"] = resulting_model_version
        if comparison is not None:
            values["comparison"] = _comparison_payload(comparison)
        entity = (
            await self._session.execute(
                update(ModelRetrainingRequest)
                .where(ModelRetrainingRequest.id == request_id)
                .values(**values)
                .returning(ModelRetrainingRequest)
            )
        ).scalar_one_or_none()
        return _request(entity) if entity is not None else None

    async def list_requests(
        self,
        *,
        registered_model_name: str | None,
        limit: int,
        offset: int,
    ) -> RetrainingRequestPage:
        conditions = []
        if registered_model_name is not None:
            conditions.append(
                ModelRetrainingRequest.registered_model_name == registered_model_name
            )
        total = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(ModelRetrainingRequest)
                    .where(*conditions)
                )
            ).scalar_one()
        )
        result = await self._session.execute(
            select(ModelRetrainingRequest)
            .where(*conditions)
            .order_by(ModelRetrainingRequest.requested_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return RetrainingRequestPage(
            tuple(_request(item) for item in result.scalars()), total
        )

    async def aggregate_status(self) -> tuple[int, int, int, int]:
        """Return global counts only; no request or user-level evidence."""
        total = await self._count()
        active = await self._count(
            ModelRetrainingRequest.request_status.in_(_ACTIVE_STATUSES)
        )
        completed = await self._count(
            ModelRetrainingRequest.request_status == RetrainingRequestStatus.COMPLETED
        )
        failed = await self._count(
            ModelRetrainingRequest.request_status == RetrainingRequestStatus.FAILED
        )
        return total, active, completed, failed

    async def list_reconcilable(self, *, limit: int) -> tuple[RetrainingRequest, ...]:
        result = await self._session.execute(
            select(ModelRetrainingRequest)
            .where(
                ModelRetrainingRequest.request_status.not_in(
                    (
                        RetrainingRequestStatus.COMPLETED,
                        RetrainingRequestStatus.FAILED,
                        RetrainingRequestStatus.CANCELLED,
                    )
                )
            )
            .order_by(ModelRetrainingRequest.updated_at, ModelRetrainingRequest.id)
            .limit(limit)
        )
        return tuple(_request(item) for item in result.scalars())

    async def create_audit(
        self,
        *,
        decision: RetrainingDecision,
        policy_id: UUID,
        evaluated_by_user_id: UUID,
        mode: RetrainingEvaluationMode,
        override_used: bool,
        override_reason: str | None,
        created_request_id: UUID | None,
        monitoring_evaluation_id: UUID | None = None,
    ) -> RetrainingAuditRecord:
        trigger = decision.trigger
        entity = ModelRetrainingAudit(
            company_id=await company_for_user(self._session, evaluated_by_user_id),
            registered_model_name=decision.registered_model_name,
            source_model_version=decision.source_model_version,
            requested_alias=decision.requested_alias,
            trigger_type=trigger.trigger_type,
            trigger_reference=trigger.reference,
            policy_id=policy_id,
            decision_status=decision.status,
            decision_reasons=list(decision.reasons),
            drift_summary={
                "aggregate_status": (
                    trigger.aggregate_status.value if trigger.aggregate_status else None
                ),
                "matched_event_count": trigger.matched_event_count,
                "analyzed_event_count": trigger.analyzed_event_count,
                "current_sample_count": trigger.current_sample_count,
                "truncated": trigger.truncated,
                "analysis_warning": trigger.analysis_warning,
            },
            thresholds=dict(trigger.thresholds),
            cooldown_state=_cooldown_payload(decision.cooldown),
            quota_state=_quota_payload(decision.quota),
            existing_request_id=decision.existing_request_id,
            created_request_id=created_request_id,
            monitoring_evaluation_id=monitoring_evaluation_id,
            evaluated_by_user_id=evaluated_by_user_id,
            evaluation_mode=mode,
            override_used=override_used,
            override_reason=override_reason,
            evaluated_at=decision.evaluated_at,
        )
        self._session.add(entity)
        await self._session.flush()
        return RetrainingAuditRecord(
            id=entity.id,
            decision=decision,
            policy_id=policy_id,
            evaluated_by_user_id=evaluated_by_user_id,
            evaluation_mode=mode,
            override_used=override_used,
            override_reason=override_reason,
            created_request_id=created_request_id,
            monitoring_evaluation_id=monitoring_evaluation_id,
        )

    async def list_audits(self, *, limit: int, offset: int) -> RetrainingAuditPage:
        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(ModelRetrainingAudit)
                )
            ).scalar_one()
        )
        result = await self._session.execute(
            select(ModelRetrainingAudit)
            .order_by(ModelRetrainingAudit.evaluated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return RetrainingAuditPage(
            tuple(_audit(item) for item in result.scalars()), total
        )

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


def _policy(entity: ModelRetrainingPolicy) -> RetrainingPolicy:
    return RetrainingPolicy(
        id=entity.id,
        registered_model_name=entity.registered_model_name,
        enabled=entity.enabled,
        allowed_trigger_types=frozenset(
            RetrainingTriggerType(item) for item in entity.allowed_trigger_types
        ),
        minimum_drift_status=entity.minimum_drift_status,
        minimum_current_sample_count=entity.minimum_current_sample_count,
        cooldown_seconds=entity.cooldown_seconds,
        maximum_requests_per_day=entity.maximum_requests_per_day,
        maximum_requests_per_week=entity.maximum_requests_per_week,
        maximum_active_requests=entity.maximum_active_requests,
        require_champion_source=entity.require_champion_source,
        allow_truncated_drift=entity.allow_truncated_drift,
        created_by_user_id=entity.created_by_user_id,
        created_at=_aware(entity.created_at),
        updated_at=_aware(entity.updated_at),
    )


def _request(entity: ModelRetrainingRequest) -> RetrainingRequest:
    return RetrainingRequest(
        id=entity.id,
        registered_model_name=entity.registered_model_name,
        source_model_version=entity.source_model_version,
        source_training_job_id=entity.source_training_job_id,
        key=TrainerKey(entity.algorithm, entity.task_type),
        trigger_type=entity.trigger_type,
        trigger_reference=entity.trigger_reference,
        policy_id=entity.policy_id,
        decision_status=entity.decision_status,
        request_status=entity.request_status,
        evaluation_mode=entity.evaluation_mode,
        idempotency_key=entity.idempotency_key,
        training_job_id=entity.training_job_id,
        monitoring_evaluation_id=entity.monitoring_evaluation_id,
        resulting_model_version=entity.resulting_model_version,
        requested_by_user_id=entity.requested_by_user_id,
        reason=entity.reason,
        override_used=entity.override_used,
        requested_at=_aware(entity.requested_at),
        started_at=_optional_aware(entity.started_at),
        completed_at=_optional_aware(entity.completed_at),
        safe_failure_code=entity.safe_failure_code,
        safe_failure_message=entity.safe_failure_message,
        comparison=_parse_comparison(entity.comparison),
        created_at=_aware(entity.created_at),
        updated_at=_aware(entity.updated_at),
    )


def _audit(entity: ModelRetrainingAudit) -> RetrainingAuditRecord:
    summary = entity.drift_summary
    raw_status = summary.get("aggregate_status")
    trigger = RetrainingTrigger(
        trigger_type=entity.trigger_type,
        reference=entity.trigger_reference,
        aggregate_status=(
            None if raw_status is None else DriftSeverity(str(raw_status))
        ),
        matched_event_count=_integer(summary["matched_event_count"]),
        analyzed_event_count=_integer(summary["analyzed_event_count"]),
        current_sample_count=_integer(summary["current_sample_count"]),
        truncated=bool(summary["truncated"]),
        analysis_warning=(
            str(summary["analysis_warning"])
            if summary.get("analysis_warning")
            else None
        ),
        thresholds=entity.thresholds,
    )
    cooldown = entity.cooldown_state
    quota = entity.quota_state
    decision = RetrainingDecision(
        registered_model_name=entity.registered_model_name,
        source_model_version=entity.source_model_version,
        requested_alias=entity.requested_alias,
        trigger=trigger,
        status=entity.decision_status,
        reasons=tuple(entity.decision_reasons),
        evaluated_at=_aware(entity.evaluated_at),
        cooldown=CooldownState(
            active=bool(cooldown["active"]),
            started_at=_parse_datetime(cooldown.get("started_at")),
            expires_at=_parse_datetime(cooldown.get("expires_at")),
            remaining_seconds=_integer(cooldown["remaining_seconds"]),
        ),
        quota=QuotaState(
            requests_today=int(quota["requests_today"]),
            requests_this_week=int(quota["requests_this_week"]),
            active_requests=int(quota["active_requests"]),
            maximum_per_day=int(quota["maximum_per_day"]),
            maximum_per_week=int(quota["maximum_per_week"]),
            maximum_active=int(quota["maximum_active"]),
        ),
        existing_request_id=entity.existing_request_id,
    )
    return RetrainingAuditRecord(
        id=entity.id,
        decision=decision,
        policy_id=entity.policy_id,
        evaluated_by_user_id=entity.evaluated_by_user_id,
        evaluation_mode=entity.evaluation_mode,
        override_used=entity.override_used,
        override_reason=entity.override_reason,
        created_request_id=entity.created_request_id,
        monitoring_evaluation_id=entity.monitoring_evaluation_id,
    )


def _comparison_payload(value: CandidateComparison | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "status": value.status.value,
        "source_model_version": value.source_model_version,
        "candidate_model_version": value.candidate_model_version,
        "compared_at": value.compared_at.isoformat(),
        "metrics": [
            {
                "metric": metric.metric,
                "source_value": metric.source_value,
                "candidate_value": metric.candidate_value,
                "higher_is_better": metric.higher_is_better,
                "outcome": metric.outcome.value,
            }
            for metric in value.metrics
        ],
    }


def _parse_comparison(value: dict[str, object] | None) -> CandidateComparison | None:
    if value is None:
        return None
    raw_metrics = value.get("metrics")
    if not isinstance(raw_metrics, list):
        raise ValueError("Persisted comparison metrics are invalid.")
    metrics: list[MetricComparison] = []
    for raw in raw_metrics:
        if not isinstance(raw, dict):
            raise ValueError("Persisted metric comparison is invalid.")
        metrics.append(
            MetricComparison(
                metric=str(raw["metric"]),
                source_value=float(raw["source_value"]),
                candidate_value=float(raw["candidate_value"]),
                higher_is_better=bool(raw["higher_is_better"]),
                outcome=ComparisonStatus(str(raw["outcome"])),
            )
        )
    return CandidateComparison(
        status=ComparisonStatus(str(value["status"])),
        metrics=tuple(metrics),
        source_model_version=str(value["source_model_version"]),
        candidate_model_version=str(value["candidate_model_version"]),
        compared_at=_aware(datetime.fromisoformat(str(value["compared_at"]))),
    )


def _cooldown_payload(value: CooldownState) -> dict[str, object]:
    return {
        "active": value.active,
        "started_at": value.started_at.isoformat() if value.started_at else None,
        "expires_at": value.expires_at.isoformat() if value.expires_at else None,
        "remaining_seconds": value.remaining_seconds,
    }


def _quota_payload(value: QuotaState) -> dict[str, int]:
    return {
        "requests_today": value.requests_today,
        "requests_this_week": value.requests_this_week,
        "active_requests": value.active_requests,
        "maximum_per_day": value.maximum_per_day,
        "maximum_per_week": value.maximum_per_week,
        "maximum_active": value.maximum_active,
    }


def _parse_datetime(value: object) -> datetime | None:
    return None if value is None else _aware(datetime.fromisoformat(str(value)))


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("Persisted retraining integer is invalid.")
    return value


def _optional_aware(value: datetime | None) -> datetime | None:
    return _aware(value) if value is not None else None


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
