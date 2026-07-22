"""Owner-scoped persistence for registered datasets and documents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.datasets.domain import DatasetKind, DatasetStatus, DatasetVersionStatus
from app.models.datasets import (
    Dataset,
    DatasetUsageReference,
    DatasetVersion,
    DocumentRecord,
)
from app.models.rag import RAGKnowledgeBase, RAGKnowledgeBaseDatasetVersion
from app.rag.domain import RAGKnowledgeBaseStatus


@dataclass(frozen=True, slots=True)
class DatasetPage:
    items: tuple[Dataset, ...]
    total: int


class DatasetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_dataset(self, **values: object) -> Dataset:
        entity = Dataset(**values)
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def create_version(self, **values: object) -> DatasetVersion:
        entity = DatasetVersion(**values)
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def claim_active_dataset_for_version(
        self, dataset_id: UUID, *, expected_version: int
    ) -> bool:
        """Serialize version creation against archival and concurrent uploads."""
        result = await self._session.execute(
            update(Dataset)
            .where(
                Dataset.id == dataset_id,
                Dataset.status == DatasetStatus.ACTIVE,
                Dataset.state_version == expected_version,
            )
            .values(
                state_version=Dataset.state_version + 1,
                updated_at=func.now(),
            )
            .returning(Dataset.id)
        )
        return result.scalar_one_or_none() is not None

    async def create_document(self, **values: object) -> DocumentRecord:
        entity = DocumentRecord(**values)
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def get_dataset(
        self, dataset_id: UUID, *, owner_id: UUID | None
    ) -> Dataset | None:
        statement = select(Dataset).where(Dataset.id == dataset_id)
        if owner_id is not None:
            statement = statement.where(Dataset.owner_user_id == owner_id)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def get_dataset_by_name(
        self, owner_id: UUID, normalized_name: str
    ) -> Dataset | None:
        return (
            await self._session.execute(
                select(Dataset).where(
                    Dataset.owner_user_id == owner_id,
                    Dataset.normalized_name == normalized_name,
                )
            )
        ).scalar_one_or_none()

    async def list_datasets(
        self,
        *,
        owner_id: UUID | None,
        kind: DatasetKind | None,
        status: DatasetStatus | None,
        limit: int,
        offset: int,
    ) -> DatasetPage:
        statement = select(Dataset)
        if owner_id is not None:
            statement = statement.where(Dataset.owner_user_id == owner_id)
        if kind is not None:
            statement = statement.where(Dataset.kind == kind)
        if status is not None:
            statement = statement.where(Dataset.status == status)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            or 0
        )
        items = (
            (
                await self._session.execute(
                    statement.order_by(Dataset.created_at.desc(), Dataset.id.asc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return DatasetPage(tuple(items), total)

    async def next_version_number(self, dataset_id: UUID) -> int:
        maximum = await self._session.scalar(
            select(func.max(DatasetVersion.version_number)).where(
                DatasetVersion.dataset_id == dataset_id
            )
        )
        return int(maximum or 0) + 1

    async def list_versions(
        self, dataset_id: UUID, *, limit: int, offset: int
    ) -> tuple[tuple[DatasetVersion, ...], int]:
        statement = select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset_id
        )
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(statement.subquery())
            )
            or 0
        )
        values = (
            (
                await self._session.execute(
                    statement.order_by(DatasetVersion.version_number.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return tuple(values), total

    async def get_version(
        self, dataset_id: UUID, version_id: UUID, *, owner_id: UUID | None
    ) -> DatasetVersion | None:
        statement = (
            select(DatasetVersion)
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .where(
                DatasetVersion.id == version_id,
                DatasetVersion.dataset_id == dataset_id,
            )
        )
        if owner_id is not None:
            statement = statement.where(Dataset.owner_user_id == owner_id)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def get_version_by_id(self, version_id: UUID) -> DatasetVersion | None:
        return await self._session.get(DatasetVersion, version_id)

    async def get_ready_tabular_version(
        self, version_id: UUID, *, owner_id: UUID | None
    ) -> DatasetVersion | None:
        statement = (
            select(DatasetVersion)
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .where(
                DatasetVersion.id == version_id,
                DatasetVersion.status == DatasetVersionStatus.READY,
                Dataset.kind == DatasetKind.TABULAR,
                Dataset.status == DatasetStatus.ACTIVE,
            )
        )
        if owner_id is not None:
            statement = statement.where(Dataset.owner_user_id == owner_id)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def get_version_reference(
        self, version_id: UUID, *, owner_id: UUID | None
    ) -> DatasetVersion | None:
        statement = (
            select(DatasetVersion)
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .where(DatasetVersion.id == version_id)
        )
        if owner_id is not None:
            statement = statement.where(Dataset.owner_user_id == owner_id)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def get_document(
        self,
        dataset_id: UUID,
        version_id: UUID,
        document_id: UUID,
        *,
        owner_id: UUID | None,
    ) -> DocumentRecord | None:
        statement = (
            select(DocumentRecord)
            .join(
                DatasetVersion, DatasetVersion.id == DocumentRecord.dataset_version_id
            )
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .where(
                DocumentRecord.id == document_id,
                DatasetVersion.id == version_id,
                Dataset.id == dataset_id,
            )
        )
        if owner_id is not None:
            statement = statement.where(Dataset.owner_user_id == owner_id)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def list_documents(
        self, version_id: UUID, *, limit: int, offset: int
    ) -> tuple[tuple[DocumentRecord, ...], int]:
        statement = select(DocumentRecord).where(
            DocumentRecord.dataset_version_id == version_id
        )
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(statement.subquery())
            )
            or 0
        )
        values = (
            (
                await self._session.execute(
                    statement.order_by(DocumentRecord.document_number.asc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return tuple(values), total

    async def claim_version(self, version_id: UUID) -> DatasetVersion | None:
        return (
            await self._session.execute(
                update(DatasetVersion)
                .where(
                    DatasetVersion.id == version_id,
                    DatasetVersion.status == DatasetVersionStatus.PENDING,
                )
                .values(
                    status=DatasetVersionStatus.PROCESSING,
                    state_version=DatasetVersion.state_version + 1,
                    processing_started_at=func.now(),
                )
                .returning(DatasetVersion)
            )
        ).scalar_one_or_none()

    async def mark_version_ready(
        self,
        version_id: UUID,
        *,
        expected_version: int,
        values: dict[str, object],
    ) -> DatasetVersion | None:
        return (
            await self._session.execute(
                update(DatasetVersion)
                .where(
                    DatasetVersion.id == version_id,
                    DatasetVersion.status == DatasetVersionStatus.PROCESSING,
                    DatasetVersion.state_version == expected_version,
                )
                .values(
                    status=DatasetVersionStatus.READY,
                    ready_at=func.now(),
                    state_version=DatasetVersion.state_version + 1,
                    **values,
                )
                .returning(DatasetVersion)
            )
        ).scalar_one_or_none()

    async def mark_version_failed(
        self, version_id: UUID, *, error_code: str, safe_error_message: str
    ) -> None:
        await self._session.execute(
            update(DatasetVersion)
            .where(
                DatasetVersion.id == version_id,
                DatasetVersion.status.in_(
                    [DatasetVersionStatus.PENDING, DatasetVersionStatus.PROCESSING]
                ),
            )
            .values(
                status=DatasetVersionStatus.FAILED,
                failed_at=func.now(),
                error_code=error_code,
                safe_error_message=safe_error_message,
                state_version=DatasetVersion.state_version + 1,
            )
        )

    async def release_version_for_retry(
        self,
        version_id: UUID,
        *,
        expected_version: int,
        safe_error_message: str,
    ) -> bool:
        result = await self._session.execute(
            update(DatasetVersion)
            .where(
                DatasetVersion.id == version_id,
                DatasetVersion.status == DatasetVersionStatus.PROCESSING,
                DatasetVersion.state_version == expected_version,
            )
            .values(
                status=DatasetVersionStatus.PENDING,
                processing_started_at=None,
                error_code="processing_retry_pending",
                safe_error_message=safe_error_message,
                state_version=DatasetVersion.state_version + 1,
            )
            .returning(DatasetVersion.id)
        )
        return result.scalar_one_or_none() is not None

    async def list_stale_processing_ids(
        self, *, before: datetime, maximum_enqueue_attempts: int, limit: int
    ) -> tuple[UUID, ...]:
        values = await self._session.scalars(
            select(DatasetVersion.id)
            .where(
                or_(
                    and_(
                        DatasetVersion.status == DatasetVersionStatus.PROCESSING,
                        DatasetVersion.processing_started_at < before,
                    ),
                    and_(
                        DatasetVersion.status == DatasetVersionStatus.PENDING,
                        DatasetVersion.error_code.in_(
                            (
                                "processing_retry_pending",
                                "stale_processing_recovered",
                            )
                        ),
                        func.coalesce(
                            DatasetVersion.last_enqueued_at,
                            DatasetVersion.created_at,
                        )
                        < before,
                    ),
                ),
                DatasetVersion.enqueue_attempt_count < maximum_enqueue_attempts,
            )
            .order_by(
                func.coalesce(
                    DatasetVersion.processing_started_at,
                    DatasetVersion.last_enqueued_at,
                    DatasetVersion.created_at,
                ).asc()
            )
            .limit(limit)
        )
        return tuple(values.all())

    async def fail_exhausted_stale_versions(
        self, *, before: datetime, maximum_enqueue_attempts: int, limit: int
    ) -> int:
        candidates = (
            select(DatasetVersion.id)
            .where(
                or_(
                    and_(
                        DatasetVersion.status == DatasetVersionStatus.PROCESSING,
                        DatasetVersion.processing_started_at < before,
                    ),
                    and_(
                        DatasetVersion.status == DatasetVersionStatus.PENDING,
                        DatasetVersion.error_code.in_(
                            (
                                "processing_retry_pending",
                                "stale_processing_recovered",
                            )
                        ),
                        func.coalesce(
                            DatasetVersion.last_enqueued_at,
                            DatasetVersion.created_at,
                        )
                        < before,
                    ),
                ),
                DatasetVersion.enqueue_attempt_count >= maximum_enqueue_attempts,
            )
            .order_by(DatasetVersion.created_at.asc(), DatasetVersion.id.asc())
            .limit(limit)
        )
        result = await self._session.execute(
            update(DatasetVersion)
            .where(
                DatasetVersion.id.in_(candidates),
                or_(
                    and_(
                        DatasetVersion.status == DatasetVersionStatus.PROCESSING,
                        DatasetVersion.processing_started_at < before,
                    ),
                    and_(
                        DatasetVersion.status == DatasetVersionStatus.PENDING,
                        DatasetVersion.error_code.in_(
                            (
                                "processing_retry_pending",
                                "stale_processing_recovered",
                            )
                        ),
                        func.coalesce(
                            DatasetVersion.last_enqueued_at,
                            DatasetVersion.created_at,
                        )
                        < before,
                    ),
                ),
                DatasetVersion.enqueue_attempt_count >= maximum_enqueue_attempts,
            )
            .values(
                status=DatasetVersionStatus.FAILED,
                failed_at=func.now(),
                error_code="processing_retries_exhausted",
                safe_error_message=(
                    "Dataset processing could not be delivered after bounded retries."
                ),
                state_version=DatasetVersion.state_version + 1,
            )
        )
        return int(cast(CursorResult[Any], result).rowcount or 0)

    async def reconcile_stale_version(
        self,
        version_id: UUID,
        *,
        before: datetime,
        maximum_enqueue_attempts: int,
    ) -> bool:
        result = await self._session.execute(
            update(DatasetVersion)
            .where(
                DatasetVersion.id == version_id,
                or_(
                    and_(
                        DatasetVersion.status == DatasetVersionStatus.PROCESSING,
                        DatasetVersion.processing_started_at < before,
                    ),
                    and_(
                        DatasetVersion.status == DatasetVersionStatus.PENDING,
                        DatasetVersion.error_code.in_(
                            (
                                "processing_retry_pending",
                                "stale_processing_recovered",
                            )
                        ),
                        func.coalesce(
                            DatasetVersion.last_enqueued_at,
                            DatasetVersion.created_at,
                        )
                        < before,
                    ),
                ),
                DatasetVersion.enqueue_attempt_count < maximum_enqueue_attempts,
            )
            .values(
                status=DatasetVersionStatus.PENDING,
                processing_started_at=None,
                last_enqueued_at=func.now(),
                enqueue_attempt_count=DatasetVersion.enqueue_attempt_count + 1,
                error_code="stale_processing_recovered",
                safe_error_message="Dataset processing was safely queued for retry.",
                state_version=DatasetVersion.state_version + 1,
            )
            .returning(DatasetVersion.id)
        )
        return result.scalar_one_or_none() is not None

    async def set_current_version(
        self, dataset_id: UUID, version_id: UUID, *, expected_version: int
    ) -> bool:
        new_version = aliased(DatasetVersion)
        current_version = aliased(DatasetVersion)
        new_number = (
            select(new_version.version_number)
            .where(
                new_version.id == version_id,
                new_version.dataset_id == dataset_id,
                new_version.status == DatasetVersionStatus.READY,
            )
            .scalar_subquery()
        )
        current_number = (
            select(current_version.version_number)
            .where(current_version.id == Dataset.current_version_id)
            .scalar_subquery()
        )
        result = await self._session.execute(
            update(Dataset)
            .where(
                Dataset.id == dataset_id,
                Dataset.status == DatasetStatus.ACTIVE,
                Dataset.state_version == expected_version,
                new_number.is_not(None),
                or_(
                    Dataset.current_version_id.is_(None),
                    current_number <= new_number,
                ),
            )
            .values(
                current_version_id=version_id,
                state_version=Dataset.state_version + 1,
                updated_at=func.now(),
            )
            .returning(Dataset.id)
        )
        return result.scalar_one_or_none() is not None

    async def archive_dataset(
        self, dataset_id: UUID, *, expected_version: int
    ) -> Dataset | None:
        active_version_work = exists(
            select(DatasetVersion.id).where(
                DatasetVersion.dataset_id == dataset_id,
                DatasetVersion.status.in_(
                    (DatasetVersionStatus.PENDING, DatasetVersionStatus.PROCESSING)
                ),
            )
        )
        active_knowledge_base_reference = exists(
            select(RAGKnowledgeBaseDatasetVersion.knowledge_base_id)
            .join(
                DatasetVersion,
                DatasetVersion.id == RAGKnowledgeBaseDatasetVersion.dataset_version_id,
            )
            .join(
                RAGKnowledgeBase,
                RAGKnowledgeBase.id == RAGKnowledgeBaseDatasetVersion.knowledge_base_id,
            )
            .where(
                DatasetVersion.dataset_id == dataset_id,
                RAGKnowledgeBase.status != RAGKnowledgeBaseStatus.ARCHIVED,
            )
        )
        return (
            await self._session.execute(
                update(Dataset)
                .where(
                    Dataset.id == dataset_id,
                    Dataset.status == DatasetStatus.ACTIVE,
                    Dataset.state_version == expected_version,
                    ~active_version_work,
                    ~active_knowledge_base_reference,
                )
                .values(
                    status=DatasetStatus.ARCHIVED,
                    archived_at=func.now(),
                    updated_at=func.now(),
                    state_version=Dataset.state_version + 1,
                )
                .returning(Dataset)
            )
        ).scalar_one_or_none()

    async def add_usage_reference(
        self, *, version_id: UUID, usage_type: str, reference_id: UUID
    ) -> None:
        self._session.add(
            DatasetUsageReference(
                dataset_version_id=version_id,
                usage_type=usage_type,
                reference_id=reference_id,
            )
        )
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def refresh(self, value: object) -> None:
        await self._session.refresh(value)
