"""SQL persistence with owner and knowledge-base scoping applied in queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.datasets.domain import (
    DatasetKind,
    DatasetStatus,
    DatasetVersionStatus,
    DocumentProcessingStatus,
)
from app.models.datasets import (
    Dataset,
    DatasetUsageReference,
    DatasetVersion,
    DocumentRecord,
)
from app.models.rag import (
    RAGChunkEmbedding,
    RAGConversation,
    RAGIndexBuild,
    RAGIndexedChunk,
    RAGKnowledgeBase,
    RAGKnowledgeBaseDatasetVersion,
    RAGMessage,
    RAGMessageCitation,
)
from app.rag.chunking import TextChunk
from app.rag.domain import (
    RAGConversationStatus,
    RAGIndexBuildStatus,
    RAGKnowledgeBaseStatus,
    RAGMessageRole,
    RAGMessageStatus,
)


@dataclass(frozen=True, slots=True)
class EntityPage[T]:
    items: tuple[T, ...]
    total: int


@dataclass(frozen=True, slots=True)
class AuthorizedDatasetVersion:
    version: DatasetVersion
    dataset_id: UUID
    dataset_state_version: int


@dataclass(frozen=True, slots=True)
class RegisteredDocument:
    entity: DocumentRecord
    version: DatasetVersion


@dataclass(frozen=True, slots=True)
class StoredRetrievalCandidate:
    embedding: RAGChunkEmbedding
    chunk: RAGIndexedChunk
    document: DocumentRecord
    score: float | None = None


class RAGRepository:
    """Centralize every RAG ownership predicate and lifecycle write."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def refresh(self, entity: object) -> None:
        await self._session.refresh(entity)

    async def create_knowledge_base(self, **values: object) -> RAGKnowledgeBase:
        entity = RAGKnowledgeBase(**values)
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def find_knowledge_base_by_name(
        self, *, owner_user_id: UUID, normalized_name: str
    ) -> RAGKnowledgeBase | None:
        return (
            await self._session.execute(
                select(RAGKnowledgeBase).where(
                    RAGKnowledgeBase.owner_user_id == owner_user_id,
                    RAGKnowledgeBase.normalized_name == normalized_name,
                )
            )
        ).scalar_one_or_none()

    async def get_knowledge_base(
        self, *, knowledge_base_id: UUID, user_id: UUID, is_admin: bool
    ) -> RAGKnowledgeBase | None:
        statement = select(RAGKnowledgeBase).where(
            RAGKnowledgeBase.id == knowledge_base_id
        )
        if not is_admin:
            statement = statement.where(RAGKnowledgeBase.owner_user_id == user_id)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def list_knowledge_bases(
        self,
        *,
        user_id: UUID,
        is_admin: bool,
        status: RAGKnowledgeBaseStatus | None,
        limit: int,
        offset: int,
    ) -> EntityPage[RAGKnowledgeBase]:
        statement = select(RAGKnowledgeBase)
        if not is_admin:
            statement = statement.where(RAGKnowledgeBase.owner_user_id == user_id)
        if status is not None:
            statement = statement.where(RAGKnowledgeBase.status == status)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            or 0
        )
        rows = (
            (
                await self._session.execute(
                    statement.order_by(
                        RAGKnowledgeBase.created_at.desc(),
                        RAGKnowledgeBase.id.asc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return EntityPage(tuple(rows), total)

    async def update_knowledge_base(
        self,
        *,
        knowledge_base_id: UUID,
        expected_version: int,
        values: dict[str, object],
    ) -> RAGKnowledgeBase | None:
        return (
            await self._session.execute(
                update(RAGKnowledgeBase)
                .where(
                    RAGKnowledgeBase.id == knowledge_base_id,
                    RAGKnowledgeBase.state_version == expected_version,
                )
                .values(
                    **values,
                    state_version=RAGKnowledgeBase.state_version + 1,
                )
                .returning(RAGKnowledgeBase)
            )
        ).scalar_one_or_none()

    async def list_attachments(
        self, knowledge_base_id: UUID
    ) -> tuple[RAGKnowledgeBaseDatasetVersion, ...]:
        rows = (
            (
                await self._session.execute(
                    select(RAGKnowledgeBaseDatasetVersion)
                    .where(
                        RAGKnowledgeBaseDatasetVersion.knowledge_base_id
                        == knowledge_base_id
                    )
                    .order_by(
                        RAGKnowledgeBaseDatasetVersion.attached_at.asc(),
                        RAGKnowledgeBaseDatasetVersion.dataset_version_id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        return tuple(rows)

    async def count_attachments(self, knowledge_base_id: UUID) -> int:
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(RAGKnowledgeBaseDatasetVersion)
                .where(
                    RAGKnowledgeBaseDatasetVersion.knowledge_base_id
                    == knowledge_base_id
                )
            )
            or 0
        )

    async def get_authorized_ready_document_version(
        self, *, dataset_version_id: UUID, required_owner_id: UUID
    ) -> AuthorizedDatasetVersion | None:
        row = (
            await self._session.execute(
                select(DatasetVersion, Dataset.id, Dataset.state_version)
                .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
                .where(
                    DatasetVersion.id == dataset_version_id,
                    Dataset.owner_user_id == required_owner_id,
                    Dataset.kind == DatasetKind.DOCUMENT_COLLECTION,
                    Dataset.status == DatasetStatus.ACTIVE,
                    DatasetVersion.status == DatasetVersionStatus.READY,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        return AuthorizedDatasetVersion(
            version=row[0],
            dataset_id=row[1],
            dataset_state_version=row[2],
        )

    async def claim_active_dataset_for_attachment(
        self,
        *,
        dataset_id: UUID,
        expected_version: int,
    ) -> bool:
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

    async def attach_dataset_version(
        self, *, knowledge_base_id: UUID, dataset_version_id: UUID
    ) -> RAGKnowledgeBaseDatasetVersion:
        entity = RAGKnowledgeBaseDatasetVersion(
            knowledge_base_id=knowledge_base_id,
            dataset_version_id=dataset_version_id,
        )
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def ensure_dataset_usage_reference(
        self, *, dataset_version_id: UUID, knowledge_base_id: UUID
    ) -> None:
        exists = await self._session.scalar(
            select(func.count())
            .select_from(DatasetUsageReference)
            .where(
                DatasetUsageReference.dataset_version_id == dataset_version_id,
                DatasetUsageReference.usage_type == "rag_knowledge_base",
                DatasetUsageReference.reference_id == knowledge_base_id,
            )
        )
        if exists:
            return
        self._session.add(
            DatasetUsageReference(
                dataset_version_id=dataset_version_id,
                usage_type="rag_knowledge_base",
                reference_id=knowledge_base_id,
            )
        )
        await self._session.flush()

    async def attachment_exists(
        self, *, knowledge_base_id: UUID, dataset_version_id: UUID
    ) -> bool:
        return (
            await self._session.scalar(
                select(func.count())
                .select_from(RAGKnowledgeBaseDatasetVersion)
                .where(
                    RAGKnowledgeBaseDatasetVersion.knowledge_base_id
                    == knowledge_base_id,
                    RAGKnowledgeBaseDatasetVersion.dataset_version_id
                    == dataset_version_id,
                )
            )
            or 0
        ) > 0

    async def detach_dataset_version(
        self, *, knowledge_base_id: UUID, dataset_version_id: UUID
    ) -> bool:
        result = await self._session.execute(
            delete(RAGKnowledgeBaseDatasetVersion).where(
                RAGKnowledgeBaseDatasetVersion.knowledge_base_id == knowledge_base_id,
                RAGKnowledgeBaseDatasetVersion.dataset_version_id == dataset_version_id,
            )
        )
        return bool(cast(CursorResult[tuple[object]], result).rowcount)

    async def create_build(
        self, *, knowledge_base_id: UUID, requested_by_user_id: UUID
    ) -> RAGIndexBuild:
        entity = RAGIndexBuild(
            knowledge_base_id=knowledge_base_id,
            requested_by_user_id=requested_by_user_id,
            status=RAGIndexBuildStatus.QUEUED,
        )
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def get_build(
        self,
        *,
        build_id: UUID,
        user_id: UUID,
        is_admin: bool,
    ) -> RAGIndexBuild | None:
        statement = (
            select(RAGIndexBuild)
            .join(
                RAGKnowledgeBase,
                RAGKnowledgeBase.id == RAGIndexBuild.knowledge_base_id,
            )
            .where(RAGIndexBuild.id == build_id)
        )
        if not is_admin:
            statement = statement.where(RAGKnowledgeBase.owner_user_id == user_id)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def get_build_internal(self, build_id: UUID) -> RAGIndexBuild | None:
        """Load a persisted build for the trusted UUID-only worker boundary."""
        return await self._session.get(RAGIndexBuild, build_id)

    async def list_builds(
        self,
        *,
        knowledge_base_id: UUID,
        limit: int,
        offset: int,
    ) -> EntityPage[RAGIndexBuild]:
        statement = select(RAGIndexBuild).where(
            RAGIndexBuild.knowledge_base_id == knowledge_base_id
        )
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            or 0
        )
        rows = (
            (
                await self._session.execute(
                    statement.order_by(
                        RAGIndexBuild.created_at.desc(), RAGIndexBuild.id.asc()
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return EntityPage(tuple(rows), total)

    async def latest_active_build(
        self, knowledge_base_id: UUID
    ) -> RAGIndexBuild | None:
        return (
            await self._session.execute(
                select(RAGIndexBuild)
                .where(
                    RAGIndexBuild.knowledge_base_id == knowledge_base_id,
                    RAGIndexBuild.status.in_(
                        (RAGIndexBuildStatus.QUEUED, RAGIndexBuildStatus.RUNNING)
                    ),
                )
                .order_by(RAGIndexBuild.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def list_stale_active_builds(
        self,
        *,
        queued_before: datetime,
        running_before: datetime,
        limit: int,
    ) -> tuple[RAGIndexBuild, ...]:
        """Return a bounded reconciliation batch without loading document data."""
        rows = (
            (
                await self._session.execute(
                    select(RAGIndexBuild)
                    .where(
                        or_(
                            and_(
                                RAGIndexBuild.status == RAGIndexBuildStatus.QUEUED,
                                func.coalesce(
                                    RAGIndexBuild.last_enqueued_at,
                                    RAGIndexBuild.created_at,
                                )
                                < queued_before,
                            ),
                            and_(
                                RAGIndexBuild.status == RAGIndexBuildStatus.RUNNING,
                                RAGIndexBuild.started_at.is_not(None),
                                RAGIndexBuild.started_at < running_before,
                            ),
                        )
                    )
                    .order_by(RAGIndexBuild.created_at.asc(), RAGIndexBuild.id.asc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return tuple(rows)

    async def record_build_enqueue_attempt(
        self,
        *,
        build_id: UUID,
        expected_version: int,
        maximum_attempts: int,
        stale_before: datetime | None = None,
    ) -> RAGIndexBuild | None:
        predicates = [
            RAGIndexBuild.id == build_id,
            RAGIndexBuild.status == RAGIndexBuildStatus.QUEUED,
            RAGIndexBuild.state_version == expected_version,
            RAGIndexBuild.enqueue_attempt_count < maximum_attempts,
        ]
        if stale_before is not None:
            predicates.append(
                func.coalesce(
                    RAGIndexBuild.last_enqueued_at,
                    RAGIndexBuild.created_at,
                )
                < stale_before
            )
        return (
            await self._session.execute(
                update(RAGIndexBuild)
                .where(*predicates)
                .values(
                    last_enqueued_at=func.now(),
                    enqueue_attempt_count=RAGIndexBuild.enqueue_attempt_count + 1,
                    state_version=RAGIndexBuild.state_version + 1,
                )
                .returning(RAGIndexBuild)
            )
        ).scalar_one_or_none()

    async def fail_exhausted_queued_build(
        self,
        *,
        build_id: UUID,
        expected_version: int,
        maximum_attempts: int,
        stale_before: datetime,
        error_code: str,
        safe_error_message: str,
    ) -> RAGIndexBuild | None:
        """Fail only the exact still-stale queued attempt selected by reconciliation."""
        return (
            await self._session.execute(
                update(RAGIndexBuild)
                .where(
                    RAGIndexBuild.id == build_id,
                    RAGIndexBuild.status == RAGIndexBuildStatus.QUEUED,
                    RAGIndexBuild.state_version == expected_version,
                    RAGIndexBuild.enqueue_attempt_count >= maximum_attempts,
                    func.coalesce(
                        RAGIndexBuild.last_enqueued_at,
                        RAGIndexBuild.created_at,
                    )
                    < stale_before,
                )
                .values(
                    status=RAGIndexBuildStatus.FAILED,
                    finished_at=func.now(),
                    error_code=error_code,
                    safe_error_message=safe_error_message,
                    state_version=RAGIndexBuild.state_version + 1,
                )
                .returning(RAGIndexBuild)
            )
        ).scalar_one_or_none()

    async def transition_build(
        self,
        *,
        build_id: UUID,
        expected_status: RAGIndexBuildStatus,
        expected_version: int,
        new_status: RAGIndexBuildStatus,
        values: dict[str, object],
    ) -> RAGIndexBuild | None:
        return (
            await self._session.execute(
                update(RAGIndexBuild)
                .where(
                    RAGIndexBuild.id == build_id,
                    RAGIndexBuild.status == expected_status,
                    RAGIndexBuild.state_version == expected_version,
                )
                .values(
                    status=new_status,
                    state_version=RAGIndexBuild.state_version + 1,
                    **values,
                )
                .returning(RAGIndexBuild)
            )
        ).scalar_one_or_none()

    async def list_registered_documents_for_build(
        self,
        *,
        knowledge_base_id: UUID,
        owner_user_id: UUID,
        maximum_documents: int,
    ) -> tuple[RegisteredDocument, ...]:
        rows = (
            await self._session.execute(
                select(DocumentRecord, DatasetVersion)
                .join(
                    DatasetVersion,
                    DatasetVersion.id == DocumentRecord.dataset_version_id,
                )
                .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
                .join(
                    RAGKnowledgeBaseDatasetVersion,
                    and_(
                        RAGKnowledgeBaseDatasetVersion.dataset_version_id
                        == DatasetVersion.id,
                        RAGKnowledgeBaseDatasetVersion.knowledge_base_id
                        == knowledge_base_id,
                    ),
                )
                .where(
                    Dataset.owner_user_id == owner_user_id,
                    Dataset.kind == DatasetKind.DOCUMENT_COLLECTION,
                    Dataset.status == DatasetStatus.ACTIVE,
                    DatasetVersion.status == DatasetVersionStatus.READY,
                    DocumentRecord.status == DocumentProcessingStatus.READY,
                    DocumentRecord.extracted_text.is_not(None),
                )
                .order_by(
                    DatasetVersion.id.asc(),
                    DocumentRecord.document_number.asc(),
                    DocumentRecord.id.asc(),
                )
                .limit(maximum_documents + 1)
            )
        ).all()
        return tuple(RegisteredDocument(entity=row[0], version=row[1]) for row in rows)

    async def add_index_entries(
        self,
        *,
        knowledge_base_id: UUID,
        build_id: UUID,
        document: DocumentRecord,
        chunks: tuple[TextChunk, ...],
        embeddings: tuple[tuple[float, ...], ...],
    ) -> None:
        for chunk, vector in zip(chunks, embeddings, strict=True):
            indexed_chunk = RAGIndexedChunk(
                knowledge_base_id=knowledge_base_id,
                index_build_id=build_id,
                document_id=document.id,
                dataset_version_id=document.dataset_version_id,
                chunk_number=chunk.chunk_number,
                content=chunk.content,
                content_hash=chunk.content_hash,
                character_count=len(chunk.content),
                page_number=None,
                section=None,
            )
            self._session.add(indexed_chunk)
            await self._session.flush()
            self._session.add(
                RAGChunkEmbedding(
                    knowledge_base_id=knowledge_base_id,
                    index_build_id=build_id,
                    chunk_id=indexed_chunk.id,
                    document_id=document.id,
                    dataset_version_id=document.dataset_version_id,
                    embedding_dimension=len(vector),
                    embedding=list(vector),
                    content_hash=chunk.content_hash,
                )
            )
        await self._session.flush()

    async def list_retrieval_candidates(
        self,
        *,
        knowledge_base_id: UUID,
        active_build_id: UUID,
        user_id: UUID,
        is_admin: bool,
        query_embedding: tuple[float, ...],
        top_k: int,
        min_score: float,
        maximum_candidates: int,
    ) -> tuple[StoredRetrievalCandidate, ...]:
        # Every ownership, attachment, readiness, and active-build predicate is
        # applied before ranking. PostgreSQL performs exact pgvector cosine ranking
        # inside that authorized scope; SQLite uses the bounded fallback below.
        base_statement = (
            select(RAGChunkEmbedding, RAGIndexedChunk, DocumentRecord)
            .join(
                RAGIndexedChunk,
                RAGIndexedChunk.id == RAGChunkEmbedding.chunk_id,
            )
            .join(DocumentRecord, DocumentRecord.id == RAGIndexedChunk.document_id)
            .join(
                DatasetVersion,
                DatasetVersion.id == RAGIndexedChunk.dataset_version_id,
            )
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .join(
                RAGKnowledgeBaseDatasetVersion,
                and_(
                    RAGKnowledgeBaseDatasetVersion.knowledge_base_id
                    == RAGChunkEmbedding.knowledge_base_id,
                    RAGKnowledgeBaseDatasetVersion.dataset_version_id
                    == DatasetVersion.id,
                ),
            )
            .join(
                RAGKnowledgeBase,
                RAGKnowledgeBase.id == RAGChunkEmbedding.knowledge_base_id,
            )
            .where(
                RAGChunkEmbedding.knowledge_base_id == knowledge_base_id,
                RAGChunkEmbedding.index_build_id == active_build_id,
                RAGKnowledgeBase.active_index_build_id == active_build_id,
                RAGKnowledgeBase.status == RAGKnowledgeBaseStatus.READY,
                Dataset.owner_user_id == RAGKnowledgeBase.owner_user_id,
                Dataset.kind == DatasetKind.DOCUMENT_COLLECTION,
                Dataset.status == DatasetStatus.ACTIVE,
                DatasetVersion.status == DatasetVersionStatus.READY,
                DocumentRecord.status == DocumentProcessingStatus.READY,
            )
        )
        if not is_admin:
            base_statement = base_statement.where(
                RAGKnowledgeBase.owner_user_id == user_id
            )

        if self._session.get_bind().dialect.name == "postgresql":
            embedding_column = cast(Any, RAGChunkEmbedding.embedding)
            distance = embedding_column.cosine_distance(list(query_embedding))
            score = (1.0 - distance).label("similarity_score")
            statement = (
                base_statement.add_columns(score)
                .where(distance <= 1.0 - min_score)
                .order_by(distance.asc(), RAGChunkEmbedding.chunk_id.asc())
                .limit(top_k)
            )
            rows = (await self._session.execute(statement)).all()
            return tuple(
                StoredRetrievalCandidate(
                    embedding=row[0],
                    chunk=row[1],
                    document=row[2],
                    score=float(row[3]),
                )
                for row in rows
            )

        rows = (
            await self._session.execute(
                base_statement.order_by(RAGChunkEmbedding.chunk_id.asc()).limit(
                    maximum_candidates + 1
                )
            )
        ).all()
        return tuple(
            StoredRetrievalCandidate(embedding=row[0], chunk=row[1], document=row[2])
            for row in rows
        )

    async def create_conversation(self, **values: object) -> RAGConversation:
        entity = RAGConversation(**values)
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def get_conversation(
        self, *, conversation_id: UUID, user_id: UUID, is_admin: bool
    ) -> RAGConversation | None:
        statement = select(RAGConversation).where(RAGConversation.id == conversation_id)
        if not is_admin:
            statement = statement.where(RAGConversation.owner_user_id == user_id)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def list_conversations(
        self,
        *,
        user_id: UUID,
        is_admin: bool,
        status: RAGConversationStatus | None,
        limit: int,
        offset: int,
    ) -> EntityPage[RAGConversation]:
        statement = select(RAGConversation)
        if not is_admin:
            statement = statement.where(RAGConversation.owner_user_id == user_id)
        if status is not None:
            statement = statement.where(RAGConversation.status == status)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            or 0
        )
        rows = (
            (
                await self._session.execute(
                    statement.order_by(
                        RAGConversation.updated_at.desc(), RAGConversation.id.asc()
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return EntityPage(tuple(rows), total)

    async def archive_conversation(
        self, *, conversation_id: UUID, expected_version: int, archived_at: datetime
    ) -> RAGConversation | None:
        return (
            await self._session.execute(
                update(RAGConversation)
                .where(
                    RAGConversation.id == conversation_id,
                    RAGConversation.status == RAGConversationStatus.ACTIVE,
                    RAGConversation.state_version == expected_version,
                )
                .values(
                    status=RAGConversationStatus.ARCHIVED,
                    archived_at=archived_at,
                    updated_at=archived_at,
                    state_version=RAGConversation.state_version + 1,
                )
                .returning(RAGConversation)
            )
        ).scalar_one_or_none()

    async def touch_conversation(
        self, *, conversation_id: UUID, expected_version: int, updated_at: datetime
    ) -> RAGConversation | None:
        return (
            await self._session.execute(
                update(RAGConversation)
                .where(
                    RAGConversation.id == conversation_id,
                    RAGConversation.state_version == expected_version,
                )
                .values(
                    updated_at=updated_at,
                    state_version=RAGConversation.state_version + 1,
                )
                .returning(RAGConversation)
            )
        ).scalar_one_or_none()

    async def create_message(self, **values: object) -> RAGMessage:
        entity = RAGMessage(**values)
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def find_idempotent_user_message(
        self, *, conversation_id: UUID, idempotency_key: str
    ) -> RAGMessage | None:
        return (
            await self._session.execute(
                select(RAGMessage).where(
                    RAGMessage.conversation_id == conversation_id,
                    RAGMessage.role == RAGMessageRole.USER,
                    RAGMessage.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()

    async def get_assistant_reply(self, user_message_id: UUID) -> RAGMessage | None:
        return (
            await self._session.execute(
                select(RAGMessage)
                .options(selectinload(RAGMessage.citations))
                .where(
                    RAGMessage.reply_to_message_id == user_message_id,
                    RAGMessage.role == RAGMessageRole.ASSISTANT,
                )
            )
        ).scalar_one_or_none()

    async def get_message(
        self, *, message_id: UUID, user_id: UUID, is_admin: bool
    ) -> RAGMessage | None:
        statement = (
            select(RAGMessage)
            .options(selectinload(RAGMessage.citations))
            .join(
                RAGConversation,
                RAGConversation.id == RAGMessage.conversation_id,
            )
            .where(RAGMessage.id == message_id)
        )
        if not is_admin:
            statement = statement.where(RAGConversation.owner_user_id == user_id)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def list_messages(
        self, *, conversation_id: UUID, limit: int, offset: int
    ) -> EntityPage[RAGMessage]:
        statement = select(RAGMessage).where(
            RAGMessage.conversation_id == conversation_id
        )
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            or 0
        )
        rows = (
            (
                await self._session.execute(
                    statement.options(selectinload(RAGMessage.citations))
                    .order_by(RAGMessage.created_at.asc(), RAGMessage.id.asc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return EntityPage(tuple(rows), total)

    async def fail_stale_messages(self, *, before: datetime, limit: int) -> int:
        """Terminalize a bounded batch left active by interrupted requests."""
        stale_ids = (
            select(RAGMessage.id)
            .where(
                RAGMessage.role == RAGMessageRole.ASSISTANT,
                RAGMessage.status.in_(
                    (RAGMessageStatus.RETRIEVING, RAGMessageStatus.GENERATING)
                ),
                RAGMessage.created_at < before,
            )
            .order_by(RAGMessage.created_at.asc(), RAGMessage.id.asc())
            .limit(limit)
        )
        message = "The grounded answer was interrupted and can be retried."
        result = await self._session.execute(
            update(RAGMessage)
            .where(
                RAGMessage.id.in_(stale_ids),
                RAGMessage.role == RAGMessageRole.ASSISTANT,
                RAGMessage.status.in_(
                    (RAGMessageStatus.RETRIEVING, RAGMessageStatus.GENERATING)
                ),
                RAGMessage.created_at < before,
            )
            .values(
                status=RAGMessageStatus.FAILED,
                content=message,
                character_count=len(message),
                completed_at=func.now(),
                error_code="generation_interrupted",
                safe_error_message=message,
            )
        )
        return int(cast(CursorResult[Any], result).rowcount or 0)

    async def recent_succeeded_message_content(
        self, *, conversation_id: UUID, limit: int
    ) -> tuple[str, ...]:
        rows = (
            await self._session.execute(
                select(RAGMessage.content)
                .where(
                    RAGMessage.conversation_id == conversation_id,
                    RAGMessage.status == RAGMessageStatus.SUCCEEDED,
                )
                .order_by(RAGMessage.created_at.desc(), RAGMessage.id.desc())
                .limit(limit)
            )
        ).scalars()
        return tuple(reversed(rows.all()))

    async def transition_message(
        self,
        *,
        message_id: UUID,
        expected_status: RAGMessageStatus,
        new_status: RAGMessageStatus,
        values: dict[str, object],
    ) -> RAGMessage | None:
        return (
            await self._session.execute(
                update(RAGMessage)
                .where(
                    RAGMessage.id == message_id,
                    RAGMessage.status == expected_status,
                )
                .values(status=new_status, **values)
                .returning(RAGMessage)
            )
        ).scalar_one_or_none()

    async def fail_active_message(
        self, *, message_id: UUID, values: dict[str, object]
    ) -> RAGMessage | None:
        return (
            await self._session.execute(
                update(RAGMessage)
                .where(
                    RAGMessage.id == message_id,
                    RAGMessage.status.in_(
                        (
                            RAGMessageStatus.QUEUED,
                            RAGMessageStatus.RETRIEVING,
                            RAGMessageStatus.GENERATING,
                        )
                    ),
                )
                .values(status=RAGMessageStatus.FAILED, **values)
                .returning(RAGMessage)
            )
        ).scalar_one_or_none()

    async def cancel_message(
        self, *, message_id: UUID, completed_at: datetime
    ) -> RAGMessage | None:
        return (
            await self._session.execute(
                update(RAGMessage)
                .where(
                    RAGMessage.id == message_id,
                    RAGMessage.status.in_(
                        (
                            RAGMessageStatus.QUEUED,
                            RAGMessageStatus.RETRIEVING,
                            RAGMessageStatus.GENERATING,
                        )
                    ),
                )
                .values(
                    status=RAGMessageStatus.CANCELLED,
                    completed_at=completed_at,
                    error_code=None,
                    safe_error_message=None,
                )
                .returning(RAGMessage)
            )
        ).scalar_one_or_none()

    async def add_citations(
        self, *, message_id: UUID, citations: tuple[dict[str, object], ...]
    ) -> None:
        self._session.add_all(
            RAGMessageCitation(message_id=message_id, **values) for values in citations
        )
        await self._session.flush()
