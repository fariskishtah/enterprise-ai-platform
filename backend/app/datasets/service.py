"""Application services for safe dataset registration and processing."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import PurePath
from typing import BinaryIO
from uuid import UUID

from anyio import fail_after, to_thread
from sqlalchemy.exc import IntegrityError

from app.datasets.domain import (
    DatasetKind,
    DatasetLineage,
    DatasetSourceType,
    DatasetStatus,
    DatasetVersionStatus,
    DocumentProcessingStatus,
    IngestionOptions,
    ProcessingResult,
)
from app.datasets.ingestion import (
    DatasetIngestionError,
    ingest_csv,
    ingest_plain_text,
    tabular_training_snapshot,
)
from app.datasets.queue import DatasetProcessingQueue
from app.datasets.storage import (
    DatasetObjectStorage,
    DatasetStorageError,
)
from app.models.datasets import Dataset, DatasetVersion, DocumentRecord
from app.observability.logging import emit_safe
from app.observability.metrics import (
    record_dataset_lifecycle,
    record_dataset_processing,
    record_process_timeout,
    record_reconciliation_repair,
)
from app.observability.tracing import traced_async_operation
from app.repositories.datasets import DatasetPage, DatasetRepository
from app.utils.safe_text import ensure_safe_single_line
from app.utils.security import utc_now

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("app.security.audit")
_DATASET_PROCESSING_TIMEOUT_SECONDS = 30.0


class DatasetNotFoundError(ValueError):
    pass


class DatasetConflictError(ValueError):
    pass


class DatasetValidationError(ValueError):
    pass


class DatasetQueueError(RuntimeError):
    pass


class RetryableDatasetProcessingError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DatasetLimits:
    upload_bytes: int
    maximum_rows: int
    maximum_columns: int
    maximum_cell_characters: int
    maximum_document_characters: int
    stale_after_seconds: int
    maximum_enqueue_attempts: int = 3


@dataclass(frozen=True, slots=True)
class DatasetTrainingSnapshot:
    dataset_id: UUID
    dataset_version_id: UUID
    schema_snapshot: dict[str, object]
    training_features: tuple[tuple[float | int, ...], ...]
    training_targets: tuple[float | int, ...]
    evaluation_features: tuple[tuple[float | int, ...], ...]
    evaluation_targets: tuple[float | int, ...]


class DatasetService:
    """Owner-scoped registry operations with immutable version creation."""

    def __init__(
        self,
        *,
        repository: DatasetRepository,
        storage: DatasetObjectStorage,
        queue: DatasetProcessingQueue,
        limits: DatasetLimits,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._queue = queue
        self._limits = limits

    async def create_dataset(
        self,
        *,
        owner_user_id: UUID,
        company_id: UUID | None = None,
        name: str,
        description: str | None,
        kind: DatasetKind,
    ) -> Dataset:
        normalized_name = " ".join(name.split()).casefold()
        resolved_company_id = company_id or owner_user_id
        if await self._repository.get_dataset_by_name(
            resolved_company_id, normalized_name
        ):
            raise DatasetConflictError("A dataset with this name already exists.")
        try:
            dataset = await self._repository.create_dataset(
                owner_user_id=owner_user_id,
                company_id=resolved_company_id,
                name=" ".join(name.split()),
                normalized_name=normalized_name,
                description=description.strip() if description is not None else None,
                kind=kind,
                status=DatasetStatus.ACTIVE,
                state_version=0,
            )
            await self._repository.commit()
        except IntegrityError as exc:
            await self._repository.rollback()
            raise DatasetConflictError(
                "A dataset with this name already exists."
            ) from exc
        record_dataset_lifecycle(
            dataset_kind=kind.value,
            event="dataset_created",
            final_status=DatasetStatus.ACTIVE.value,
        )
        self._audit("dataset_created", "succeeded", kind)
        return dataset

    async def get_dataset(self, dataset_id: UUID, *, owner_id: UUID | None) -> Dataset:
        dataset = await self._repository.get_dataset(dataset_id, owner_id=owner_id)
        if dataset is None:
            self._audit_hidden("dataset")
            raise DatasetNotFoundError("Dataset not found.")
        return dataset

    async def list_datasets(
        self,
        *,
        owner_id: UUID | None,
        kind: DatasetKind | None,
        status: DatasetStatus | None,
        limit: int,
        offset: int,
    ) -> DatasetPage:
        return await self._repository.list_datasets(
            owner_id=owner_id,
            kind=kind,
            status=status,
            limit=limit,
            offset=offset,
        )

    @traced_async_operation("dataset.upload_storage")
    async def create_version(
        self,
        *,
        dataset_id: UUID,
        owner_id: UUID | None,
        created_by_user_id: UUID,
        source: BinaryIO,
        filename: str,
        media_type: str,
        options: IngestionOptions,
    ) -> DatasetVersion:
        dataset = await self.get_dataset(dataset_id, owner_id=owner_id)
        if dataset.status is not DatasetStatus.ACTIVE:
            raise DatasetConflictError("Archived datasets cannot accept new versions.")
        safe_filename = _validated_filename(filename)
        normalized_media_type = media_type.partition(";")[0].strip().casefold()
        _validate_upload_contract(dataset.kind, safe_filename, normalized_media_type)

        try:
            stored = await to_thread.run_sync(
                lambda: self._storage.write(
                    source,
                    maximum_bytes=self._limits.upload_bytes,
                )
            )
        except (DatasetStorageError, OSError) as exc:
            raise DatasetValidationError(
                "The upload could not be stored safely."
            ) from exc
        if stored.size_bytes < 1:
            await to_thread.run_sync(lambda: self._storage.delete(stored.key))
            raise DatasetValidationError("Dataset uploads cannot be empty.")

        try:
            claimed = await self._repository.claim_active_dataset_for_version(
                dataset.id,
                expected_version=dataset.state_version,
            )
        except Exception:
            await self._repository.rollback()
            await to_thread.run_sync(lambda: self._storage.delete(stored.key))
            raise
        if not claimed:
            await self._repository.rollback()
            await to_thread.run_sync(lambda: self._storage.delete(stored.key))
            raise DatasetConflictError(
                "The dataset changed while the upload was stored; retry the operation."
            )

        lineage = DatasetLineage(source_type=DatasetSourceType.UPLOAD)
        try:
            version = await self._repository.create_version(
                dataset_id=dataset.id,
                version_number=await self._repository.next_version_number(dataset.id),
                status=DatasetVersionStatus.PENDING,
                source_type=DatasetSourceType.UPLOAD,
                storage_key=stored.key,
                original_filename=safe_filename,
                media_type=normalized_media_type,
                size_bytes=stored.size_bytes,
                sha256_digest=stored.sha256_digest,
                schema_snapshot={},
                lineage_snapshot=lineage.model_dump(mode="json"),
                ingestion_options=options.model_dump(mode="json"),
                processing_summary={},
                created_by_user_id=created_by_user_id,
                last_enqueued_at=utc_now(),
                enqueue_attempt_count=1,
                state_version=0,
            )
            await self._repository.commit()
        except IntegrityError as exc:
            await self._repository.rollback()
            await to_thread.run_sync(lambda: self._storage.delete(stored.key))
            raise DatasetConflictError(
                "This dataset content is already registered as a version."
            ) from exc
        except Exception:
            await self._repository.rollback()
            await to_thread.run_sync(lambda: self._storage.delete(stored.key))
            raise

        try:
            self._queue.enqueue(version.id)
        except Exception as exc:
            await self._repository.mark_version_failed(
                version.id,
                error_code="enqueue_failed",
                safe_error_message="Dataset processing could not be queued.",
            )
            await self._repository.commit()
            await to_thread.run_sync(lambda: self._storage.delete(stored.key))
            record_dataset_lifecycle(
                dataset_kind=dataset.kind.value,
                event="version_created",
                final_status=DatasetVersionStatus.FAILED.value,
            )
            self._audit("dataset_processing_failed", "failed", dataset.kind)
            raise DatasetQueueError("Dataset processing could not be queued.") from exc
        record_dataset_lifecycle(
            dataset_kind=dataset.kind.value,
            event="version_created",
            final_status=DatasetVersionStatus.PENDING.value,
        )
        self._audit("dataset_version_created", "accepted", dataset.kind)
        return version

    async def get_version(
        self,
        *,
        dataset_id: UUID,
        version_id: UUID,
        owner_id: UUID | None,
    ) -> DatasetVersion:
        version = await self._repository.get_version(
            dataset_id, version_id, owner_id=owner_id
        )
        if version is None:
            self._audit_hidden("dataset_version")
            raise DatasetNotFoundError("Dataset version not found.")
        return version

    async def list_versions(
        self,
        *,
        dataset_id: UUID,
        owner_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[tuple[DatasetVersion, ...], int]:
        await self.get_dataset(dataset_id, owner_id=owner_id)
        return await self._repository.list_versions(
            dataset_id, limit=limit, offset=offset
        )

    async def list_documents(
        self,
        *,
        dataset_id: UUID,
        version_id: UUID,
        owner_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[tuple[DocumentRecord, ...], int]:
        version = await self.get_version(
            dataset_id=dataset_id,
            version_id=version_id,
            owner_id=owner_id,
        )
        if version.media_type != "text/plain":
            raise DatasetConflictError("This version does not contain documents.")
        return await self._repository.list_documents(
            version_id, limit=limit, offset=offset
        )

    async def get_document(
        self,
        *,
        dataset_id: UUID,
        version_id: UUID,
        document_id: UUID,
        owner_id: UUID | None,
    ) -> DocumentRecord:
        document = await self._repository.get_document(
            dataset_id,
            version_id,
            document_id,
            owner_id=owner_id,
        )
        if document is None:
            self._audit_hidden("document")
            raise DatasetNotFoundError("Document not found.")
        return document

    async def archive_dataset(
        self, dataset_id: UUID, *, owner_id: UUID | None
    ) -> Dataset:
        current = await self.get_dataset(dataset_id, owner_id=owner_id)
        if current.status is DatasetStatus.ARCHIVED:
            return current
        archived = await self._repository.archive_dataset(
            dataset_id, expected_version=current.state_version
        )
        if archived is None:
            await self._repository.rollback()
            raise DatasetConflictError(
                "Finish active processing and detach the dataset from active "
                "knowledge bases before archiving."
            )
        await self._repository.commit()
        record_dataset_lifecycle(
            dataset_kind=current.kind.value,
            event="dataset_archived",
            final_status=DatasetStatus.ARCHIVED.value,
        )
        self._audit("dataset_archived", "succeeded", current.kind)
        return archived

    @traced_async_operation("training.dataset_resolution")
    async def resolve_training_snapshot(
        self, version_id: UUID, *, owner_id: UUID | None
    ) -> DatasetTrainingSnapshot:
        version = await self._repository.get_version_reference(
            version_id, owner_id=owner_id
        )
        if version is None:
            self._audit_hidden("dataset_version")
            raise DatasetNotFoundError("Dataset version not found.")
        dataset = await self._repository.get_dataset(
            version.dataset_id, owner_id=owner_id
        )
        if dataset is None:
            raise DatasetNotFoundError("Dataset version not found.")
        if (
            dataset.kind is not DatasetKind.TABULAR
            or dataset.status is not DatasetStatus.ACTIVE
            or version.status is not DatasetVersionStatus.READY
        ):
            raise DatasetConflictError(
                "Training requires a ready tabular dataset version."
            )
        try:
            payload = await to_thread.run_sync(
                lambda: self._storage.read(
                    version.storage_key,
                    maximum_bytes=self._limits.upload_bytes,
                )
            )
        except (DatasetStorageError, OSError) as exc:
            raise DatasetQueueError(
                "The registered dataset is temporarily unavailable."
            ) from exc
        if hashlib.sha256(payload).hexdigest() != version.sha256_digest:
            raise DatasetQueueError(
                "The registered dataset failed integrity verification."
            )
        options = IngestionOptions.model_validate(version.ingestion_options)
        try:
            with fail_after(_DATASET_PROCESSING_TIMEOUT_SECONDS):
                training_x, training_y, evaluation_x, evaluation_y = (
                    await to_thread.run_sync(
                        lambda: tabular_training_snapshot(
                            payload,
                            schema_snapshot=version.schema_snapshot,
                            evaluation_fraction=options.evaluation_fraction,
                        ),
                        abandon_on_cancel=True,
                    )
                )
        except TimeoutError as exc:
            record_process_timeout(workload="dataset_processing")
            raise DatasetQueueError(
                "The registered dataset could not be resolved in time."
            ) from exc
        except DatasetIngestionError as exc:
            raise DatasetConflictError(
                "The registered dataset is not compatible with numeric training."
            ) from exc
        return DatasetTrainingSnapshot(
            dataset_id=dataset.id,
            dataset_version_id=version.id,
            schema_snapshot=dict(version.schema_snapshot),
            training_features=tuple(tuple(row) for row in training_x),
            training_targets=tuple(training_y),
            evaluation_features=tuple(tuple(row) for row in evaluation_x),
            evaluation_targets=tuple(evaluation_y),
        )

    def _audit(self, event: str, outcome: str, kind: DatasetKind) -> None:
        emit_safe(
            audit_logger,
            logging.INFO,
            "security_audit",
            extra={
                "audit_event": event,
                "outcome": outcome,
                "resource_kind": kind.value,
            },
        )

    def _audit_hidden(self, resource_kind: str) -> None:
        emit_safe(
            audit_logger,
            logging.WARNING,
            "security_audit",
            extra={
                "audit_event": "dataset_resource_access_denied",
                "outcome": "denied",
                "resource_kind": resource_kind,
            },
        )


class DatasetProcessor:
    """Idempotent worker-side processor for one authoritative version UUID."""

    def __init__(
        self,
        *,
        repository: DatasetRepository,
        storage: DatasetObjectStorage,
        limits: DatasetLimits,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._limits = limits

    @traced_async_operation("dataset.version_creation")
    async def process(self, version_id: UUID) -> bool:
        claimed = await self._repository.claim_version(version_id)
        if claimed is None:
            await self._repository.rollback()
            return False
        await self._repository.commit()
        dataset = await self._repository.get_dataset(claimed.dataset_id, owner_id=None)
        if dataset is None:
            await self._terminal_failure(
                claimed,
                dataset_kind="unknown",
                code="dataset_missing",
                message="The parent dataset is unavailable.",
            )
            return True
        started = utc_now()
        try:
            payload = await to_thread.run_sync(
                lambda: self._storage.read(
                    claimed.storage_key,
                    maximum_bytes=self._limits.upload_bytes,
                )
            )
            if hashlib.sha256(payload).hexdigest() != claimed.sha256_digest:
                raise DatasetStorageError("Stored object digest mismatch.")
            options = IngestionOptions.model_validate(claimed.ingestion_options)
            if dataset.kind is DatasetKind.TABULAR:
                with fail_after(_DATASET_PROCESSING_TIMEOUT_SECONDS):
                    result = await to_thread.run_sync(
                        lambda: ingest_csv(
                            payload,
                            maximum_rows=self._limits.maximum_rows,
                            maximum_columns=self._limits.maximum_columns,
                            maximum_cell_characters=(
                                self._limits.maximum_cell_characters
                            ),
                            target_column=options.target_column,
                            split_column=options.split_column,
                        ),
                        abandon_on_cancel=True,
                    )
                values: dict[str, object] = {
                    "row_count": result.row_count,
                    "column_count": result.column_count,
                    "document_count": None,
                    "chunk_count": None,
                    "schema_snapshot": result.schema_snapshot,
                    "processing_summary": ProcessingResult(
                        row_count=result.row_count,
                        column_count=result.column_count,
                    ).model_dump(mode="json"),
                    "error_code": None,
                    "safe_error_message": None,
                }
            else:
                with fail_after(_DATASET_PROCESSING_TIMEOUT_SECONDS):
                    result = await to_thread.run_sync(
                        lambda: ingest_plain_text(
                            payload,
                            maximum_characters=(
                                self._limits.maximum_document_characters
                            ),
                        ),
                        abandon_on_cancel=True,
                    )
                assert result.document_text is not None
                now = utc_now()
                await self._repository.create_document(
                    dataset_version_id=claimed.id,
                    document_number=1,
                    title=PurePath(claimed.original_filename or "document.txt").stem[
                        :255
                    ],
                    source_filename=claimed.original_filename or "document.txt",
                    media_type=claimed.media_type,
                    size_bytes=claimed.size_bytes,
                    sha256_digest=claimed.sha256_digest,
                    page_count=None,
                    extracted_character_count=len(result.document_text),
                    status=DocumentProcessingStatus.READY,
                    extracted_text=result.document_text,
                    processing_started_at=claimed.processing_started_at,
                    ready_at=now,
                )
                values = {
                    "row_count": None,
                    "column_count": None,
                    "document_count": 1,
                    "chunk_count": 0,
                    "schema_snapshot": result.schema_snapshot,
                    "processing_summary": ProcessingResult(
                        document_count=1,
                        chunk_count=0,
                    ).model_dump(mode="json"),
                    "error_code": None,
                    "safe_error_message": None,
                }
            ready = await self._repository.mark_version_ready(
                claimed.id,
                expected_version=claimed.state_version,
                values=values,
            )
            if ready is None:
                await self._repository.rollback()
                return False
            current_updated = await self._repository.set_current_version(
                dataset.id,
                ready.id,
                expected_version=dataset.state_version,
            )
            await self._repository.commit()
            if not current_updated:
                # A concurrent version may have updated the dataset first. The ready
                # version remains immutable and valid; retry the pointer once without
                # rolling back the successfully processed version.
                current = await self._repository.get_dataset(dataset.id, owner_id=None)
                if current is not None:
                    await self._repository.set_current_version(
                        current.id,
                        ready.id,
                        expected_version=current.state_version,
                    )
                    await self._repository.commit()
        except TimeoutError:
            await self._repository.rollback()
            record_process_timeout(workload="dataset_processing")
            await self._terminal_failure(
                claimed,
                dataset_kind=dataset.kind.value,
                code="processing_timeout",
                message="Dataset processing exceeded the safe time limit.",
            )
            return True
        except DatasetIngestionError as exc:
            await self._repository.rollback()
            await self._terminal_failure(
                claimed,
                dataset_kind=dataset.kind.value,
                code="validation_failed",
                message=str(exc),
            )
            return True
        except RetryableDatasetProcessingError:
            raise
        except (DatasetStorageError, OSError) as exc:
            await self._repository.rollback()
            released = await self._repository.release_version_for_retry(
                claimed.id,
                expected_version=claimed.state_version,
                safe_error_message="Dataset storage is temporarily unavailable.",
            )
            if released:
                await self._repository.commit()
            else:
                await self._repository.rollback()
            raise RetryableDatasetProcessingError(
                "Dataset storage is temporarily unavailable."
            ) from exc
        duration = max(0.0, (utc_now() - started).total_seconds())
        record_dataset_processing(
            dataset_kind=dataset.kind.value,
            stage=(
                "validation" if dataset.kind is DatasetKind.TABULAR else "extraction"
            ),
            final_status="succeeded",
            duration_seconds=duration,
        )
        record_dataset_lifecycle(
            dataset_kind=dataset.kind.value,
            event="processing_terminal",
            final_status=DatasetVersionStatus.READY.value,
        )
        emit_safe(
            audit_logger,
            logging.INFO,
            "security_audit",
            extra={
                "audit_event": "dataset_processing_completed",
                "outcome": "succeeded",
                "resource_kind": dataset.kind.value,
            },
        )
        return True

    async def reconcile_stale(self, queue: DatasetProcessingQueue) -> int:
        before = utc_now() - timedelta(seconds=self._limits.stale_after_seconds)
        exhausted = await self._repository.fail_exhausted_stale_versions(
            before=before,
            maximum_enqueue_attempts=self._limits.maximum_enqueue_attempts,
            limit=100,
        )
        if exhausted:
            await self._repository.commit()
            record_reconciliation_repair(
                workload="dataset_processing",
                outcome="failed",
                count=exhausted,
            )
        ids = await self._repository.list_stale_processing_ids(
            before=before,
            maximum_enqueue_attempts=self._limits.maximum_enqueue_attempts,
            limit=100,
        )
        repaired = 0
        for version_id in ids:
            if not await self._repository.reconcile_stale_version(
                version_id,
                before=before,
                maximum_enqueue_attempts=self._limits.maximum_enqueue_attempts,
            ):
                continue
            await self._repository.commit()
            try:
                queue.enqueue(version_id)
            except Exception:
                record_reconciliation_repair(
                    workload="dataset_processing", outcome="failed"
                )
                continue
            repaired += 1
        if repaired:
            record_reconciliation_repair(
                workload="dataset_processing", outcome="repaired", count=repaired
            )
        return repaired

    async def _terminal_failure(
        self,
        version: DatasetVersion,
        *,
        dataset_kind: str,
        code: str,
        message: str,
    ) -> None:
        await self._repository.mark_version_failed(
            version.id,
            error_code=code,
            safe_error_message=message,
        )
        await self._repository.commit()
        record_dataset_processing(
            dataset_kind=dataset_kind,
            stage=(
                "extraction" if dataset_kind == "document_collection" else "validation"
            ),
            final_status="failed",
            duration_seconds=0.0,
        )
        record_dataset_lifecycle(
            dataset_kind=dataset_kind,
            event="processing_terminal",
            final_status=DatasetVersionStatus.FAILED.value,
        )
        emit_safe(
            audit_logger,
            logging.WARNING,
            "security_audit",
            extra={
                "audit_event": "dataset_processing_failed",
                "outcome": "failed",
                "resource_kind": dataset_kind,
                "reason": code,
            },
        )


def _validated_filename(filename: str) -> str:
    value = filename.strip()
    if (
        not value
        or len(value) > 255
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\x00" in value
        or "\r" in value
        or "\n" in value
    ):
        raise DatasetValidationError("The upload filename is invalid.")
    try:
        ensure_safe_single_line(value)
    except ValueError as exc:
        raise DatasetValidationError("The upload filename is invalid.") from exc
    return value


def _validate_upload_contract(
    kind: DatasetKind, filename: str, media_type: str
) -> None:
    suffix = PurePath(filename).suffix.casefold()
    expected = (
        (".csv", "text/csv") if kind is DatasetKind.TABULAR else (".txt", "text/plain")
    )
    if (suffix, media_type) != expected:
        supported = "CSV" if kind is DatasetKind.TABULAR else "plain-text"
        raise DatasetValidationError(f"This dataset accepts {supported} uploads only.")
