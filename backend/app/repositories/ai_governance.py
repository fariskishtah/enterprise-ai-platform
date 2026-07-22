"""Persistence boundaries for AI jobs and promotion audits."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.base import TrainerKey
from app.ml.jobs.models import (
    TrainingJobRecord,
    TrainingJobSpec,
    TrainingJobStatus,
    parse_training_job_spec,
)
from app.ml.promotion.models import (
    ModelAlias,
    ModelPromotionAuditRecord,
    PromotionAction,
    PromotionDecision,
    PromotionOperationOutcome,
)
from app.models.ai_governance import ModelPromotionAudit, TrainingJob
from app.models.datasets import DatasetUsageReference


@dataclass(frozen=True, slots=True)
class TrainingJobPage:
    """Paginated persistent job snapshots."""

    items: tuple[TrainingJobRecord, ...]
    total: int


@dataclass(frozen=True, slots=True)
class PromotionAuditPage:
    """Paginated model-promotion audit snapshots."""

    items: tuple[ModelPromotionAuditRecord, ...]
    total: int


class TrainingJobRepository:
    """Centralize job persistence and conditional lifecycle transitions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        job_id: UUID,
        requested_by_user_id: UUID,
        key: TrainerKey,
        specification: TrainingJobSpec,
        idempotency_key: str | None,
        request_fingerprint: str,
        max_attempts: int,
        queued_at: datetime,
    ) -> TrainingJobRecord:
        """Create one authoritative queued job."""
        entity = TrainingJob(
            id=job_id,
            requested_by_user_id=requested_by_user_id,
            dataset_version_id=specification.dataset_version_id,
            algorithm=key.algorithm,
            task_type=key.task_type,
            status=TrainingJobStatus.QUEUED,
            specification=specification.payload(),
            experiment_name=specification.experiment_name,
            run_name=specification.run_name,
            registered_model_name=specification.registered_model_name,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            max_attempts=max_attempts,
            queued_at=queued_at,
        )
        self._session.add(entity)
        await self._session.flush()
        if specification.dataset_version_id is not None:
            self._session.add(
                DatasetUsageReference(
                    dataset_version_id=specification.dataset_version_id,
                    usage_type="training_job",
                    reference_id=entity.id,
                )
            )
            await self._session.flush()
        await self._session.refresh(entity)
        return _job_record(entity)

    async def get_by_id(self, job_id: UUID) -> TrainingJobRecord | None:
        """Return one job without applying authorization scope."""
        entity = await self._session.get(TrainingJob, job_id)
        return _job_record(entity) if entity is not None else None

    async def get_idempotent(
        self,
        *,
        requested_by_user_id: UUID,
        key: TrainerKey,
        idempotency_key: str,
    ) -> TrainingJobRecord | None:
        """Resolve one persisted idempotency scope."""
        statement = select(TrainingJob).where(
            TrainingJob.requested_by_user_id == requested_by_user_id,
            TrainingJob.algorithm == key.algorithm,
            TrainingJob.task_type == key.task_type,
            TrainingJob.idempotency_key == idempotency_key,
        )
        entity = (await self._session.execute(statement)).scalar_one_or_none()
        return _job_record(entity) if entity is not None else None

    async def set_queue_identifier(
        self,
        *,
        job_id: UUID,
        queue_message_id: str,
        expected_version: int,
    ) -> TrainingJobRecord | None:
        """Attach a broker ID once using queued state and optimistic versioning."""
        statement = (
            update(TrainingJob)
            .where(
                TrainingJob.id == job_id,
                TrainingJob.status == TrainingJobStatus.QUEUED,
                TrainingJob.queue_message_id.is_(None),
                TrainingJob.state_version == expected_version,
            )
            .values(
                queue_message_id=queue_message_id,
                state_version=TrainingJob.state_version + 1,
                error_code=None,
                safe_error_message=None,
            )
            .returning(TrainingJob)
        )
        entity = (await self._session.execute(statement)).scalar_one_or_none()
        return _job_record(entity) if entity is not None else None

    async def mark_queue_identifier_pending(
        self,
        *,
        job_id: UUID,
        expected_version: int,
    ) -> TrainingJobRecord | None:
        """Record that an already-enqueued job needs message-ID reconciliation."""
        return await self._conditional_update(
            job_id=job_id,
            expected_status=TrainingJobStatus.QUEUED,
            expected_version=expected_version,
            values={
                "error_code": "queue_message_persistence_pending",
                "safe_error_message": (
                    "The queue message identifier requires reconciliation."
                ),
            },
        )

    async def claim_queued(
        self,
        *,
        job_id: UUID,
        started_at: datetime,
    ) -> TrainingJobRecord | None:
        """Atomically let one worker move a queued job to running."""
        statement = (
            update(TrainingJob)
            .where(
                TrainingJob.id == job_id,
                TrainingJob.status == TrainingJobStatus.QUEUED,
                TrainingJob.attempt_count < TrainingJob.max_attempts,
            )
            .values(
                status=TrainingJobStatus.RUNNING,
                started_at=started_at,
                attempt_count=TrainingJob.attempt_count + 1,
                state_version=TrainingJob.state_version + 1,
                error_code=None,
                safe_error_message=None,
            )
            .returning(TrainingJob)
        )
        entity = (await self._session.execute(statement)).scalar_one_or_none()
        return _job_record(entity) if entity is not None else None

    async def release_for_retry(
        self,
        *,
        job_id: UUID,
        expected_version: int,
        error_code: str,
        safe_error_message: str,
        queued_at: datetime,
    ) -> TrainingJobRecord | None:
        """Return a running transient failure to the queued state."""
        return await self._conditional_update(
            job_id=job_id,
            expected_status=TrainingJobStatus.RUNNING,
            expected_version=expected_version,
            values={
                "status": TrainingJobStatus.QUEUED,
                "queued_at": queued_at,
                "error_code": error_code,
                "safe_error_message": safe_error_message,
            },
        )

    async def mark_succeeded(
        self,
        *,
        job_id: UUID,
        expected_version: int,
        finished_at: datetime,
        local_execution_run_id: UUID,
        mlflow_experiment_id: str,
        mlflow_run_id: str,
        registered_model_version: str,
        metrics: Mapping[str, float],
    ) -> TrainingJobRecord | None:
        """Atomically persist all successful external execution metadata."""
        return await self._conditional_update(
            job_id=job_id,
            expected_status=TrainingJobStatus.RUNNING,
            expected_version=expected_version,
            values={
                "status": TrainingJobStatus.SUCCEEDED,
                "finished_at": finished_at,
                "local_execution_run_id": local_execution_run_id,
                "mlflow_experiment_id": mlflow_experiment_id,
                "mlflow_run_id": mlflow_run_id,
                "registered_model_version": registered_model_version,
                "metrics": dict(metrics),
                "error_code": None,
                "safe_error_message": None,
            },
        )

    async def record_external_result(
        self,
        *,
        job_id: UUID,
        expected_version: int,
        local_execution_run_id: UUID,
        mlflow_experiment_id: str,
        mlflow_run_id: str,
        registered_model_version: str,
        metrics: Mapping[str, float],
    ) -> TrainingJobRecord | None:
        """Checkpoint a registered version before its candidate alias is assigned."""
        return await self._conditional_update(
            job_id=job_id,
            expected_status=TrainingJobStatus.RUNNING,
            expected_version=expected_version,
            values={
                "local_execution_run_id": local_execution_run_id,
                "mlflow_experiment_id": mlflow_experiment_id,
                "mlflow_run_id": mlflow_run_id,
                "registered_model_version": registered_model_version,
                "metrics": dict(metrics),
            },
        )

    async def mark_failed(
        self,
        *,
        job_id: UUID,
        expected_status: TrainingJobStatus,
        error_code: str,
        safe_error_message: str,
        finished_at: datetime,
        expected_version: int | None = None,
    ) -> TrainingJobRecord | None:
        """Persist a sanitized terminal failure from queued or running."""
        return await self._conditional_update(
            job_id=job_id,
            expected_status=expected_status,
            expected_version=expected_version,
            values={
                "status": TrainingJobStatus.FAILED,
                "finished_at": finished_at,
                "error_code": error_code,
                "safe_error_message": safe_error_message,
            },
        )

    async def cancel_queued(
        self,
        *,
        job_id: UUID,
        cancelled_at: datetime,
    ) -> TrainingJobRecord | None:
        """Atomically cancel only a job that has not been claimed."""
        return await self._conditional_update(
            job_id=job_id,
            expected_status=TrainingJobStatus.QUEUED,
            values={
                "status": TrainingJobStatus.CANCELLED,
                "cancelled_at": cancelled_at,
                "finished_at": cancelled_at,
            },
        )

    async def list_jobs(
        self,
        *,
        requested_by_user_id: UUID | None,
        status: TrainingJobStatus | None,
        limit: int,
        offset: int,
    ) -> TrainingJobPage:
        """Return newest jobs in an optional owner and status scope."""
        statement = select(TrainingJob)
        if requested_by_user_id is not None:
            statement = statement.where(
                TrainingJob.requested_by_user_id == requested_by_user_id,
            )
        if status is not None:
            statement = statement.where(TrainingJob.status == status)
        count = await self._session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery()),
        )
        result = await self._session.execute(
            statement.order_by(TrainingJob.created_at.desc(), TrainingJob.id.asc())
            .limit(limit)
            .offset(offset),
        )
        return TrainingJobPage(
            items=tuple(_job_record(entity) for entity in result.scalars()),
            total=count or 0,
        )

    async def find_succeeded_model_version(
        self,
        *,
        registered_model_name: str,
        registered_model_version: str,
    ) -> TrainingJobRecord | None:
        """Return promotion evidence for one completed background version."""
        statement = select(TrainingJob).where(
            TrainingJob.status == TrainingJobStatus.SUCCEEDED,
            TrainingJob.registered_model_name == registered_model_name,
            TrainingJob.registered_model_version == registered_model_version,
        )
        entity = (await self._session.execute(statement)).scalar_one_or_none()
        return _job_record(entity) if entity is not None else None

    async def requeue_stale(
        self,
        *,
        stale_before: datetime,
        queued_at: datetime,
    ) -> tuple[UUID, ...]:
        """Atomically release bounded stale running jobs for administrative enqueue."""
        statement = (
            update(TrainingJob)
            .where(
                TrainingJob.status == TrainingJobStatus.RUNNING,
                TrainingJob.started_at < stale_before,
                TrainingJob.attempt_count < TrainingJob.max_attempts,
            )
            .values(
                status=TrainingJobStatus.QUEUED,
                queued_at=queued_at,
                queue_message_id=None,
                state_version=TrainingJob.state_version + 1,
                error_code="worker_stale",
                safe_error_message=(
                    "The worker execution became stale and was requeued."
                ),
            )
            .returning(TrainingJob.id)
        )
        result = await self._session.execute(statement)
        return tuple(result.scalars())

    async def list_orphaned_queued(
        self,
        *,
        queued_before: datetime,
    ) -> tuple[TrainingJobRecord, ...]:
        """Return aged queued jobs that have no persisted broker identifier."""
        statement = (
            select(TrainingJob)
            .where(
                TrainingJob.status == TrainingJobStatus.QUEUED,
                TrainingJob.queue_message_id.is_(None),
                TrainingJob.queued_at < queued_before,
            )
            .order_by(TrainingJob.queued_at.asc(), TrainingJob.id.asc())
        )
        result = await self._session.execute(statement)
        return tuple(_job_record(entity) for entity in result.scalars())

    async def fail_exhausted_stale(
        self,
        *,
        stale_before: datetime,
        finished_at: datetime,
    ) -> tuple[UUID, ...]:
        """Terminate stale claims that already consumed their bounded attempts."""
        statement = (
            update(TrainingJob)
            .where(
                TrainingJob.status == TrainingJobStatus.RUNNING,
                TrainingJob.started_at < stale_before,
                TrainingJob.attempt_count >= TrainingJob.max_attempts,
            )
            .values(
                status=TrainingJobStatus.FAILED,
                finished_at=finished_at,
                state_version=TrainingJob.state_version + 1,
                error_code="retry_exhausted",
                safe_error_message=(
                    "The stale training job exhausted its configured attempts."
                ),
            )
            .returning(TrainingJob.id)
        )
        result = await self._session.execute(statement)
        return tuple(result.scalars())

    async def commit(self) -> None:
        """Commit the active transaction."""
        await self._session.commit()

    async def rollback(self) -> None:
        """Roll back the active transaction."""
        await self._session.rollback()

    async def _conditional_update(
        self,
        *,
        job_id: UUID,
        expected_status: TrainingJobStatus,
        values: Mapping[str, object],
        expected_version: int | None = None,
    ) -> TrainingJobRecord | None:
        conditions = [
            TrainingJob.id == job_id,
            TrainingJob.status == expected_status,
        ]
        if expected_version is not None:
            conditions.append(TrainingJob.state_version == expected_version)
        statement = (
            update(TrainingJob)
            .where(*conditions)
            .values(**values, state_version=TrainingJob.state_version + 1)
            .returning(TrainingJob)
        )
        entity = (await self._session.execute(statement)).scalar_one_or_none()
        return _job_record(entity) if entity is not None else None


class ModelPromotionAuditRepository:
    """Persist append-only promotion attempts and their final outcomes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_attempt(
        self,
        *,
        registered_model_name: str,
        model_version: str,
        key: TrainerKey,
        target_alias: ModelAlias,
        previous_version: str | None,
        requested_by_user_id: UUID,
        decision: PromotionDecision,
        policy_result: Mapping[str, object],
        force: bool,
        reason: str | None,
    ) -> ModelPromotionAuditRecord:
        """Create a durable pending audit before the external alias mutation."""
        entity = ModelPromotionAudit(
            registered_model_name=registered_model_name,
            model_version=model_version,
            algorithm=key.algorithm,
            task_type=key.task_type,
            action=PromotionAction.ASSIGN_ALIAS,
            target_alias=target_alias,
            previous_version=previous_version,
            requested_by_user_id=requested_by_user_id,
            decision=decision,
            policy_result=dict(policy_result),
            force=force,
            reason=reason,
            operation_outcome=PromotionOperationOutcome.PENDING,
        )
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return _audit_record(entity)

    async def complete_attempt(
        self,
        *,
        audit_id: UUID,
        outcome: PromotionOperationOutcome,
        completed_at: datetime,
        error_code: str | None = None,
        safe_error_message: str | None = None,
    ) -> ModelPromotionAuditRecord | None:
        """Finalize only an audit that is still pending."""
        statement = (
            update(ModelPromotionAudit)
            .where(
                ModelPromotionAudit.id == audit_id,
                ModelPromotionAudit.operation_outcome
                == PromotionOperationOutcome.PENDING,
            )
            .values(
                operation_outcome=outcome,
                completed_at=completed_at,
                error_code=error_code,
                safe_error_message=safe_error_message,
            )
            .returning(ModelPromotionAudit)
        )
        entity = (await self._session.execute(statement)).scalar_one_or_none()
        return _audit_record(entity) if entity is not None else None

    async def list_pending_before(
        self,
        *,
        created_before: datetime,
    ) -> tuple[ModelPromotionAuditRecord, ...]:
        """Return aged pending alias attempts for operational reconciliation."""
        statement = (
            select(ModelPromotionAudit)
            .where(
                ModelPromotionAudit.operation_outcome
                == PromotionOperationOutcome.PENDING,
                ModelPromotionAudit.created_at < created_before,
            )
            .order_by(
                ModelPromotionAudit.created_at.asc(),
                ModelPromotionAudit.id.asc(),
            )
        )
        result = await self._session.execute(statement)
        return tuple(_audit_record(entity) for entity in result.scalars())

    async def list_for_model(
        self,
        *,
        registered_model_name: str,
        limit: int,
        offset: int,
    ) -> PromotionAuditPage:
        """Return newest audit records for a validated registered model."""
        statement = select(ModelPromotionAudit).where(
            ModelPromotionAudit.registered_model_name == registered_model_name,
        )
        count = await self._session.scalar(
            select(func.count()).select_from(statement.subquery()),
        )
        result = await self._session.execute(
            statement.order_by(
                ModelPromotionAudit.created_at.desc(),
                ModelPromotionAudit.id.asc(),
            )
            .limit(limit)
            .offset(offset),
        )
        return PromotionAuditPage(
            items=tuple(_audit_record(entity) for entity in result.scalars()),
            total=count or 0,
        )

    async def commit(self) -> None:
        """Commit the active transaction."""
        await self._session.commit()

    async def rollback(self) -> None:
        """Roll back the active transaction."""
        await self._session.rollback()


def _job_record(entity: TrainingJob) -> TrainingJobRecord:
    return TrainingJobRecord(
        id=entity.id,
        requested_by_user_id=entity.requested_by_user_id,
        dataset_version_id=entity.dataset_version_id,
        key=TrainerKey(entity.algorithm, entity.task_type),
        status=entity.status,
        specification=parse_training_job_spec(
            entity.task_type,
            entity.algorithm,
            entity.specification,
        ),
        queue_message_id=entity.queue_message_id,
        attempt_count=entity.attempt_count,
        max_attempts=entity.max_attempts,
        state_version=entity.state_version,
        created_at=entity.created_at,
        queued_at=entity.queued_at,
        started_at=entity.started_at,
        finished_at=entity.finished_at,
        cancelled_at=entity.cancelled_at,
        error_code=entity.error_code,
        safe_error_message=entity.safe_error_message,
        local_execution_run_id=entity.local_execution_run_id,
        mlflow_experiment_id=entity.mlflow_experiment_id,
        mlflow_run_id=entity.mlflow_run_id,
        registered_model_version=entity.registered_model_version,
        metrics=entity.metrics,
    )


def _audit_record(entity: ModelPromotionAudit) -> ModelPromotionAuditRecord:
    return ModelPromotionAuditRecord(
        id=entity.id,
        registered_model_name=entity.registered_model_name,
        model_version=entity.model_version,
        key=TrainerKey(entity.algorithm, entity.task_type),
        target_alias=entity.target_alias,
        previous_version=entity.previous_version,
        requested_by_user_id=entity.requested_by_user_id,
        action=entity.action,
        decision=entity.decision,
        policy_result=entity.policy_result,
        force=entity.force,
        reason=entity.reason,
        operation_outcome=entity.operation_outcome,
        created_at=entity.created_at,
        completed_at=entity.completed_at,
        error_code=entity.error_code,
        safe_error_message=entity.safe_error_message,
    )
