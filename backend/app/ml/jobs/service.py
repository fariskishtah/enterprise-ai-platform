"""Submission, query, cancellation, and recovery services for training jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from app.ml.base import TrainerKey
from app.ml.jobs.exceptions import (
    TrainingJobConflictError,
    TrainingJobEnqueueError,
    TrainingJobNotFoundError,
    TrainingJobQueuePersistenceError,
)
from app.ml.jobs.models import (
    TrainingJobRecord,
    TrainingJobSpec,
    TrainingJobStatus,
    TrainingJobSubmission,
)
from app.ml.jobs.queue import TrainingJobQueue
from app.observability.metrics import record_training_job_submitted
from app.repositories.ai_governance import TrainingJobPage, TrainingJobRepository
from app.utils.security import utc_now

type JobIdFactory = Callable[[], UUID]

logger = logging.getLogger(__name__)


class TrainingJobService:
    """Orchestrate durable submission and authorized lifecycle operations."""

    def __init__(
        self,
        *,
        repository: TrainingJobRepository,
        queue: TrainingJobQueue,
        max_attempts: int,
        job_id_factory: JobIdFactory = uuid4,
    ) -> None:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive.")
        self._repository = repository
        self._queue = queue
        self._max_attempts = max_attempts
        self._job_id_factory = job_id_factory

    async def submit(
        self,
        *,
        requested_by_user_id: UUID,
        key: TrainerKey,
        specification: TrainingJobSpec,
        idempotency_key: str | None,
    ) -> TrainingJobSubmission:
        """Persist before enqueue and expose no false success on broker failure."""
        normalized_key = _normalize_idempotency_key(idempotency_key)
        fingerprint = specification.fingerprint()
        if normalized_key is not None:
            existing = await self._repository.get_idempotent(
                requested_by_user_id=requested_by_user_id,
                key=key,
                idempotency_key=normalized_key,
            )
            if existing is not None:
                matched = _match_fingerprint(existing, fingerprint)
                _ensure_normal_submission_state(matched)
                return TrainingJobSubmission(
                    job=matched,
                    created=False,
                )

        now = utc_now()
        try:
            job = await self._repository.create(
                job_id=self._job_id_factory(),
                requested_by_user_id=requested_by_user_id,
                key=key,
                specification=specification,
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
                max_attempts=self._max_attempts,
                queued_at=now,
            )
            await self._repository.commit()
        except IntegrityError:
            await self._repository.rollback()
            if normalized_key is None:
                raise
            existing = await self._repository.get_idempotent(
                requested_by_user_id=requested_by_user_id,
                key=key,
                idempotency_key=normalized_key,
            )
            if existing is None:
                raise
            matched = _match_fingerprint(existing, fingerprint)
            _ensure_normal_submission_state(matched)
            return TrainingJobSubmission(
                job=matched,
                created=False,
            )

        try:
            message_id = self._queue.enqueue(job.id)
        except Exception as exc:
            await self._repository.rollback()
            failed = await self._repository.mark_failed(
                job_id=job.id,
                expected_status=TrainingJobStatus.QUEUED,
                error_code="enqueue_failed",
                safe_error_message=(
                    "The training job could not be submitted to the worker queue."
                ),
                finished_at=utc_now(),
            )
            if failed is not None:
                await self._repository.commit()
            raise TrainingJobEnqueueError(
                "The training job could not be submitted to the worker queue.",
            ) from exc

        try:
            persisted = await self._repository.set_queue_identifier(
                job_id=job.id,
                queue_message_id=message_id,
                expected_version=job.state_version,
            )
            if persisted is None:
                raise RuntimeError(
                    "The enqueued job changed before its message ID was persisted.",
                )
            await self._repository.commit()
        except Exception as exc:
            await self._repository.rollback()
            await self._record_queue_identifier_pending(
                job_id=job.id,
                expected_version=job.state_version,
            )
            raise TrainingJobQueuePersistenceError(
                "The queued job requires message identifier reconciliation.",
            ) from exc
        record_training_job_submitted(
            task_type=key.task_type.value,
            algorithm=key.algorithm.value,
        )
        return TrainingJobSubmission(job=persisted, created=True)

    async def _record_queue_identifier_pending(
        self,
        *,
        job_id: UUID,
        expected_version: int,
    ) -> None:
        """Best-effort durable marker; the null identifier remains authoritative."""
        try:
            pending = await self._repository.mark_queue_identifier_pending(
                job_id=job_id,
                expected_version=expected_version,
            )
            if pending is None:
                await self._repository.rollback()
                return
            await self._repository.commit()
        except Exception:
            logger.exception(
                "Could not persist queue-message reconciliation marker for job %s",
                job_id,
            )
            await self._repository.rollback()

    async def get_authorized(
        self,
        *,
        job_id: UUID,
        current_user_id: UUID,
        is_admin: bool,
    ) -> TrainingJobRecord:
        """Return a job only when it is inside the caller's scope."""
        job = await self._repository.get_by_id(job_id)
        if job is None or (
            not is_admin and job.requested_by_user_id != current_user_id
        ):
            raise TrainingJobNotFoundError("Training job not found.")
        return job

    async def list_authorized(
        self,
        *,
        current_user_id: UUID,
        is_admin: bool,
        status: TrainingJobStatus | None,
        limit: int,
        offset: int,
    ) -> TrainingJobPage:
        """List all jobs for admins and owner-only jobs for engineers."""
        return await self._repository.list_jobs(
            requested_by_user_id=None if is_admin else current_user_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def cancel(
        self,
        *,
        job_id: UUID,
        current_user_id: UUID,
        is_admin: bool,
    ) -> TrainingJobRecord:
        """Cancel only a queued job within the authorized scope."""
        current = await self.get_authorized(
            job_id=job_id,
            current_user_id=current_user_id,
            is_admin=is_admin,
        )
        if current.status is not TrainingJobStatus.QUEUED:
            raise TrainingJobConflictError(
                f"A {current.status.value} training job cannot be cancelled.",
            )
        cancelled = await self._repository.cancel_queued(
            job_id=job_id,
            cancelled_at=utc_now(),
        )
        if cancelled is None:
            await self._repository.rollback()
            raise TrainingJobConflictError(
                "The training job was claimed before cancellation completed.",
            )
        await self._repository.commit()
        return cancelled


class StaleTrainingJobRecoveryService:
    """Recover stale running and aged queued jobs without persisted message IDs."""

    def __init__(
        self,
        *,
        repository: TrainingJobRepository,
        queue: TrainingJobQueue,
        stale_after_seconds: int,
        orphaned_after_seconds: int,
    ) -> None:
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive.")
        if orphaned_after_seconds <= 0:
            raise ValueError("orphaned_after_seconds must be positive.")
        self._repository = repository
        self._queue = queue
        self._stale_after_seconds = stale_after_seconds
        self._orphaned_after_seconds = orphaned_after_seconds

    async def reconcile(self) -> tuple[UUID, ...]:
        """Release stale claims, commit them, and enqueue UUID-only replacements."""
        now = utc_now()
        stale_before = now - timedelta(seconds=self._stale_after_seconds)
        stale_job_ids = await self._repository.requeue_stale(
            stale_before=stale_before,
            queued_at=now,
        )
        await self._repository.fail_exhausted_stale(
            stale_before=stale_before,
            finished_at=now,
        )
        await self._repository.commit()
        jobs_by_id: dict[UUID, TrainingJobRecord] = {}
        for job_id in stale_job_ids:
            job = await self._repository.get_by_id(job_id)
            if job is not None:
                jobs_by_id[job.id] = job
        orphaned_before = now - timedelta(seconds=self._orphaned_after_seconds)
        for job in await self._repository.list_orphaned_queued(
            queued_before=orphaned_before,
        ):
            jobs_by_id[job.id] = job
        await self._repository.commit()
        for job in jobs_by_id.values():
            try:
                message_id = self._queue.enqueue(job.id)
            except Exception:
                logger.exception("Could not requeue training job %s", job.id)
                await self._repository.rollback()
                await self._repository.mark_failed(
                    job_id=job.id,
                    expected_status=TrainingJobStatus.QUEUED,
                    expected_version=job.state_version,
                    error_code="requeue_failed",
                    safe_error_message=(
                        "The orphaned training job could not be resubmitted."
                    ),
                    finished_at=utc_now(),
                )
                await self._repository.commit()
                continue
            try:
                updated = await self._repository.set_queue_identifier(
                    job_id=job.id,
                    queue_message_id=message_id,
                    expected_version=job.state_version,
                )
                if updated is None:
                    await self._repository.rollback()
                    continue
                await self._repository.commit()
            except Exception:
                logger.exception(
                    "Could not persist recovered queue message ID for job %s",
                    job.id,
                )
                await self._repository.rollback()
                await self._record_reconciliation_pending(job)
        return tuple(jobs_by_id)

    async def _record_reconciliation_pending(
        self,
        job: TrainingJobRecord,
    ) -> None:
        """Leave an enqueued job recoverable if its broker ID cannot be stored."""
        try:
            pending = await self._repository.mark_queue_identifier_pending(
                job_id=job.id,
                expected_version=job.state_version,
            )
            if pending is None:
                await self._repository.rollback()
                return
            await self._repository.commit()
        except Exception:
            logger.exception(
                "Could not mark recovered job %s for later reconciliation",
                job.id,
            )
            await self._repository.rollback()


def _normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 128:
        raise TrainingJobConflictError(
            "Idempotency-Key must be non-empty and at most 128 characters.",
        )
    return normalized


def _match_fingerprint(
    existing: TrainingJobRecord,
    fingerprint: str,
) -> TrainingJobRecord:
    if existing.specification.fingerprint() != fingerprint:
        raise TrainingJobConflictError(
            "The idempotency key was already used with a different request.",
        )
    return existing


def _ensure_normal_submission_state(existing: TrainingJobRecord) -> None:
    if (
        existing.status is TrainingJobStatus.QUEUED
        and existing.queue_message_id is None
    ):
        raise TrainingJobQueuePersistenceError(
            "The queued job requires message identifier reconciliation.",
        )
