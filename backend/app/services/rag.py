"""Permission-aware indexing, retrieval, and grounded chat orchestration."""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from uuid import UUID

from anyio import fail_after, to_thread
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models.rag import (
    RAGConversation,
    RAGIndexBuild,
    RAGKnowledgeBase,
    RAGKnowledgeBaseDatasetVersion,
    RAGMessage,
)
from app.observability.logging import emit_safe
from app.observability.metrics import (
    record_chatbot_generation,
    record_process_timeout,
    record_rag_index_lifecycle,
    record_rag_index_processing,
    record_rag_retrieval,
    record_reconciliation_repair,
)
from app.observability.tracing import traced_async_operation
from app.rag.chunking import ChunkingError, TextChunk, chunk_text
from app.rag.domain import (
    GroundedAnswer,
    GroundedOutcome,
    RAGConversationStatus,
    RAGIndexBuildStatus,
    RAGKnowledgeBaseStatus,
    RAGMessageRole,
    RAGMessageStatus,
    RetrievalResult,
)
from app.rag.embeddings import (
    LOCAL_EMBEDDING_DIMENSION,
    DeterministicHashEmbeddingProvider,
    EmbeddingInputError,
    EmbeddingProvider,
    cosine_similarity,
)
from app.rag.generation import (
    GroundedGenerationProvider,
    LocalExtractiveGenerationProvider,
)
from app.rag.queue import RAGIndexQueue
from app.repositories.rag import EntityPage, RAGRepository, StoredRetrievalCandidate
from app.utils.security import utc_now

_MAX_ATTACHED_DATASET_VERSIONS = 20
_MAX_DOCUMENTS_PER_BUILD = 100
_MAX_CHUNKS_PER_BUILD = 2000
_MAX_RETRIEVAL_CANDIDATES = 2000
_MAX_RECENT_MESSAGES = 10
_MAX_EXCERPT_CHARACTERS = 500
_EMBEDDING_BATCH_SIZE = 64
_LOCAL_OPERATION_TIMEOUT_SECONDS = 30.0

audit_logger = logging.getLogger("app.security.audit")


class RAGServiceError(Exception):
    """Base safe service error."""


class RAGNotFoundError(RAGServiceError):
    """Raised for absent or hidden resources."""


class RAGConflictError(RAGServiceError):
    """Raised for incompatible lifecycle or idempotency state."""


class RAGValidationError(RAGServiceError):
    """Raised for safe, user-correctable input or source data failures."""


class RAGUnavailableError(RAGServiceError):
    """Raised when persistence or processing infrastructure fails."""


@dataclass(frozen=True, slots=True)
class KnowledgeBaseDetail:
    knowledge_base: RAGKnowledgeBase
    attachments: tuple[RAGKnowledgeBaseDatasetVersion, ...]
    indexed_document_count: int
    indexed_chunk_count: int


@dataclass(frozen=True, slots=True)
class KnowledgeBasePage:
    items: tuple[KnowledgeBaseDetail, ...]
    total: int


@dataclass(frozen=True, slots=True)
class RetrievalResponse:
    knowledge_base_id: UUID
    results: tuple[RetrievalResult, ...]
    insufficient_evidence: bool


@dataclass(frozen=True, slots=True)
class MessageExchange:
    user_message: RAGMessage
    assistant_message: RAGMessage


@dataclass(frozen=True, slots=True)
class RAGReconciliationResult:
    requeued_build_count: int
    failed_stale_build_count: int
    enqueue_failure_count: int


class RAGService:
    """Coordinate only registered data through local allowlisted providers."""

    def __init__(
        self,
        repository: RAGRepository,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        generation_provider: GroundedGenerationProvider | None = None,
    ) -> None:
        self._repository = repository
        self._embedding = embedding_provider or DeterministicHashEmbeddingProvider()
        self._generation = generation_provider or LocalExtractiveGenerationProvider()
        if self._embedding.dimension != LOCAL_EMBEDDING_DIMENSION:
            raise ValueError("The configured embedding dimension is unsupported.")

    async def create_knowledge_base(
        self,
        *,
        owner_user_id: UUID,
        name: str,
        description: str | None,
        chunk_size: int,
        chunk_overlap: int,
    ) -> KnowledgeBaseDetail:
        normalized_name = " ".join(name.split()).casefold()
        if await self._repository.find_knowledge_base_by_name(
            owner_user_id=owner_user_id, normalized_name=normalized_name
        ):
            raise RAGConflictError("A knowledge base with this name already exists.")
        try:
            entity = await self._repository.create_knowledge_base(
                owner_user_id=owner_user_id,
                name=" ".join(name.split()),
                normalized_name=normalized_name,
                description=description,
                status=RAGKnowledgeBaseStatus.DRAFT,
                embedding_provider=self._embedding.provider_name,
                embedding_model=self._embedding.model_name,
                embedding_dimension=self._embedding.dimension,
                chunking_configuration={
                    "chunk_size": chunk_size,
                    "chunk_overlap": chunk_overlap,
                    "maximum_chunks": _MAX_CHUNKS_PER_BUILD,
                },
            )
            await self._repository.commit()
        except IntegrityError as exc:
            await self._repository.rollback()
            raise RAGConflictError(
                "A knowledge base with this name already exists."
            ) from exc
        emit_safe(
            audit_logger,
            logging.INFO,
            "security_audit",
            extra={"audit_event": "rag_knowledge_base_created", "outcome": "success"},
        )
        record_rag_index_lifecycle(
            event="knowledge_base_created", final_status="pending"
        )
        return KnowledgeBaseDetail(entity, (), 0, 0)

    async def get_knowledge_base_detail(
        self, *, knowledge_base_id: UUID, user_id: UUID, is_admin: bool
    ) -> KnowledgeBaseDetail:
        entity = await self._get_knowledge_base(
            knowledge_base_id=knowledge_base_id, user_id=user_id, is_admin=is_admin
        )
        return await self._detail(entity)

    async def list_knowledge_bases(
        self,
        *,
        user_id: UUID,
        is_admin: bool,
        status: RAGKnowledgeBaseStatus | None,
        limit: int,
        offset: int,
    ) -> KnowledgeBasePage:
        page = await self._repository.list_knowledge_bases(
            user_id=user_id,
            is_admin=is_admin,
            status=status,
            limit=limit,
            offset=offset,
        )
        return KnowledgeBasePage(
            items=tuple([await self._detail(item) for item in page.items]),
            total=page.total,
        )

    async def attach_dataset_version(
        self,
        *,
        knowledge_base_id: UUID,
        dataset_version_id: UUID,
        user_id: UUID,
        is_admin: bool,
    ) -> RAGKnowledgeBaseDatasetVersion:
        knowledge_base = await self._get_knowledge_base(
            knowledge_base_id=knowledge_base_id, user_id=user_id, is_admin=is_admin
        )
        self._require_mutable_knowledge_base(knowledge_base)
        version = await self._repository.get_authorized_ready_document_version(
            dataset_version_id=dataset_version_id,
            required_owner_id=knowledge_base.owner_user_id,
        )
        if version is None:
            raise RAGNotFoundError("Dataset version not found.")
        if await self._repository.attachment_exists(
            knowledge_base_id=knowledge_base.id,
            dataset_version_id=dataset_version_id,
        ):
            await self._repository.ensure_dataset_usage_reference(
                dataset_version_id=dataset_version_id,
                knowledge_base_id=knowledge_base.id,
            )
            await self._repository.commit()
            attachments = await self._repository.list_attachments(knowledge_base.id)
            return next(
                item
                for item in attachments
                if item.dataset_version_id == dataset_version_id
            )
        if (
            await self._repository.count_attachments(knowledge_base.id)
            >= _MAX_ATTACHED_DATASET_VERSIONS
        ):
            raise RAGValidationError(
                "The knowledge base has reached its dataset-version limit."
            )
        try:
            claimed = await self._repository.claim_active_dataset_for_attachment(
                dataset_id=version.dataset_id,
                expected_version=version.dataset_state_version,
            )
            if not claimed:
                raise RAGConflictError(
                    "The dataset changed before it could be attached."
                )
            attachment = await self._repository.attach_dataset_version(
                knowledge_base_id=knowledge_base.id,
                dataset_version_id=dataset_version_id,
            )
            await self._repository.ensure_dataset_usage_reference(
                dataset_version_id=dataset_version_id,
                knowledge_base_id=knowledge_base.id,
            )
            changed = await self._repository.update_knowledge_base(
                knowledge_base_id=knowledge_base.id,
                expected_version=knowledge_base.state_version,
                values={
                    "status": RAGKnowledgeBaseStatus.DRAFT,
                    "active_index_build_id": None,
                    "error_code": None,
                    "safe_error_message": None,
                    "updated_at": utc_now(),
                },
            )
            if changed is None:
                raise RAGConflictError("The knowledge base changed concurrently.")
            await self._repository.commit()
        except RAGConflictError:
            await self._repository.rollback()
            raise
        except IntegrityError as exc:
            await self._repository.rollback()
            raise RAGConflictError("The dataset version is already attached.") from exc
        emit_safe(
            audit_logger,
            logging.INFO,
            "security_audit",
            extra={"audit_event": "rag_dataset_attached", "outcome": "success"},
        )
        record_rag_index_lifecycle(event="dataset_attached", final_status="pending")
        return attachment

    async def detach_dataset_version(
        self,
        *,
        knowledge_base_id: UUID,
        dataset_version_id: UUID,
        user_id: UUID,
        is_admin: bool,
    ) -> None:
        knowledge_base = await self._get_knowledge_base(
            knowledge_base_id=knowledge_base_id, user_id=user_id, is_admin=is_admin
        )
        self._require_mutable_knowledge_base(knowledge_base)
        detached = await self._repository.detach_dataset_version(
            knowledge_base_id=knowledge_base.id,
            dataset_version_id=dataset_version_id,
        )
        if not detached:
            await self._repository.rollback()
            raise RAGNotFoundError("Dataset version attachment not found.")
        changed = await self._repository.update_knowledge_base(
            knowledge_base_id=knowledge_base.id,
            expected_version=knowledge_base.state_version,
            values={
                "status": RAGKnowledgeBaseStatus.DRAFT,
                "active_index_build_id": None,
                "error_code": None,
                "safe_error_message": None,
                "updated_at": utc_now(),
            },
        )
        if changed is None:
            await self._repository.rollback()
            raise RAGConflictError("The knowledge base changed concurrently.")
        await self._repository.commit()
        emit_safe(
            audit_logger,
            logging.INFO,
            "security_audit",
            extra={"audit_event": "rag_dataset_detached", "outcome": "success"},
        )

    async def create_build(
        self, *, knowledge_base_id: UUID, user_id: UUID, is_admin: bool
    ) -> RAGIndexBuild:
        """Persist one queued build without placing document content on a queue."""
        knowledge_base = await self._get_knowledge_base(
            knowledge_base_id=knowledge_base_id, user_id=user_id, is_admin=is_admin
        )
        self._require_mutable_knowledge_base(knowledge_base)
        if await self._repository.count_attachments(knowledge_base.id) == 0:
            raise RAGValidationError(
                "Attach at least one ready document dataset version before indexing."
            )
        if await self._repository.latest_active_build(knowledge_base.id) is not None:
            raise RAGConflictError("An index build is already active.")
        build = await self._repository.create_build(
            knowledge_base_id=knowledge_base.id,
            requested_by_user_id=user_id,
        )
        changed = await self._repository.update_knowledge_base(
            knowledge_base_id=knowledge_base.id,
            expected_version=knowledge_base.state_version,
            values={
                "status": RAGKnowledgeBaseStatus.INDEXING,
                "error_code": None,
                "safe_error_message": None,
                "updated_at": utc_now(),
            },
        )
        if changed is None:
            await self._repository.rollback()
            raise RAGConflictError("The knowledge base changed concurrently.")
        await self._repository.commit()
        record_rag_index_lifecycle(event="build_created", final_status="queued")
        emit_safe(
            audit_logger,
            logging.INFO,
            "security_audit",
            extra={"audit_event": "rag_index_requested", "outcome": "accepted"},
        )
        return build

    async def create_and_enqueue_build(
        self,
        *,
        knowledge_base_id: UUID,
        user_id: UUID,
        is_admin: bool,
        queue: RAGIndexQueue,
    ) -> RAGIndexBuild:
        """Durably create a build, then enqueue only its UUID."""
        build = await self.create_build(
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
            is_admin=is_admin,
        )
        attempted = await self._repository.record_build_enqueue_attempt(
            build_id=build.id,
            expected_version=build.state_version,
            maximum_attempts=100,
        )
        if attempted is None:
            await self._repository.rollback()
            raise RAGConflictError("The index build changed before it was queued.")
        await self._repository.commit()
        build = attempted
        try:
            queue.enqueue(build.id)
        except Exception as exc:
            await self._fail_build(
                build_id=build.id,
                knowledge_base_id=build.knowledge_base_id,
                error_code="rag_index_enqueue_failed",
                safe_message="The document index could not be queued.",
            )
            record_rag_index_lifecycle(event="build_terminal", final_status="failed")
            raise RAGUnavailableError(
                "The document index could not be queued."
            ) from exc
        return build

    async def create_and_process_build(
        self, *, knowledge_base_id: UUID, user_id: UUID, is_admin: bool
    ) -> RAGIndexBuild:
        """Synchronous bounded adapter retained for deterministic tests."""
        build = await self.create_build(
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
            is_admin=is_admin,
        )
        return await self.process_build(build.id)

    @traced_async_operation("rag.index_build")
    async def process_build(self, build_id: UUID) -> RAGIndexBuild:
        """Claim and execute one persisted build; safe for a UUID-only actor."""
        started_clock = perf_counter()
        build = await self._repository.get_build_internal(build_id)
        if build is None:
            raise RAGNotFoundError("Index build not found.")
        if build.status is not RAGIndexBuildStatus.QUEUED:
            return build
        knowledge_base = await self._repository.get_knowledge_base(
            knowledge_base_id=build.knowledge_base_id,
            user_id=build.requested_by_user_id,
            is_admin=True,
        )
        if knowledge_base is None:
            raise RAGNotFoundError("Knowledge base not found.")
        now = utc_now()
        running = await self._repository.transition_build(
            build_id=build.id,
            expected_status=RAGIndexBuildStatus.QUEUED,
            expected_version=build.state_version,
            new_status=RAGIndexBuildStatus.RUNNING,
            values={"started_at": now},
        )
        if running is None:
            await self._repository.rollback()
            current = await self._repository.get_build_internal(build.id)
            if current is None:
                raise RAGNotFoundError("Index build not found.")
            return current
        await self._repository.commit()
        record_rag_index_lifecycle(event="build_started", final_status="running")

        processing_stage = "validation"
        try:
            documents = await self._repository.list_registered_documents_for_build(
                knowledge_base_id=knowledge_base.id,
                owner_user_id=knowledge_base.owner_user_id,
                maximum_documents=_MAX_DOCUMENTS_PER_BUILD,
            )
            if not documents:
                raise RAGValidationError(
                    "No ready registered documents are available for indexing."
                )
            if len(documents) > _MAX_DOCUMENTS_PER_BUILD:
                raise RAGValidationError(
                    "The knowledge base exceeds the document limit."
                )
            chunk_size, overlap, configured_maximum = self._chunking_configuration(
                knowledge_base
            )
            maximum_chunks = min(configured_maximum, _MAX_CHUNKS_PER_BUILD)
            chunk_count = 0
            for source in documents:
                remaining = maximum_chunks - chunk_count
                if remaining <= 0:
                    raise RAGValidationError(
                        "The knowledge base exceeds the chunk limit."
                    )
                text = source.entity.extracted_text
                if text is None:
                    raise RAGValidationError(
                        "A registered document is not ready for indexing."
                    )
                processing_stage = "chunking"
                chunks = await self._chunk_document(
                    text=text,
                    chunk_size=chunk_size,
                    overlap=overlap,
                    maximum_chunks=remaining,
                )
                processing_stage = "embedding"
                vectors = await self._embed_chunks(
                    tuple(item.content for item in chunks)
                )
                processing_stage = "indexing"
                await self._repository.add_index_entries(
                    knowledge_base_id=knowledge_base.id,
                    build_id=running.id,
                    document=source.entity,
                    chunks=chunks,
                    embeddings=vectors,
                )
                chunk_count += len(chunks)

            finished_at = utc_now()
            succeeded = await self._repository.transition_build(
                build_id=running.id,
                expected_status=RAGIndexBuildStatus.RUNNING,
                expected_version=running.state_version,
                new_status=RAGIndexBuildStatus.SUCCEEDED,
                values={
                    "indexed_document_count": len(documents),
                    "indexed_chunk_count": chunk_count,
                    "embedding_count": chunk_count,
                    "finished_at": finished_at,
                    "error_code": None,
                    "safe_error_message": None,
                },
            )
            if succeeded is None:
                raise RAGConflictError("The index build changed concurrently.")
            refreshed_knowledge_base = await self._repository.get_knowledge_base(
                knowledge_base_id=knowledge_base.id,
                user_id=knowledge_base.owner_user_id,
                is_admin=True,
            )
            if refreshed_knowledge_base is None:
                raise RAGNotFoundError("Knowledge base not found.")
            changed = await self._repository.update_knowledge_base(
                knowledge_base_id=knowledge_base.id,
                expected_version=refreshed_knowledge_base.state_version,
                values={
                    "status": RAGKnowledgeBaseStatus.READY,
                    "active_index_build_id": succeeded.id,
                    "error_code": None,
                    "safe_error_message": None,
                    "updated_at": finished_at,
                },
            )
            if changed is None:
                raise RAGConflictError("The knowledge base changed concurrently.")
            await self._repository.commit()
        except (ChunkingError, EmbeddingInputError, RAGValidationError) as exc:
            await self._fail_build(
                build_id=running.id,
                knowledge_base_id=knowledge_base.id,
                error_code="rag_index_validation_failed",
                safe_message=str(exc),
            )
            duration = max(perf_counter() - started_clock, 0.0)
            record_rag_index_processing(
                stage=processing_stage,
                final_status="failed",
                duration_seconds=duration,
            )
            record_rag_index_lifecycle(event="build_terminal", final_status="failed")
            failed = await self._repository.get_build_internal(running.id)
            if failed is None:
                raise RAGNotFoundError("Index build not found.") from exc
            return failed
        except (SQLAlchemyError, RAGConflictError) as exc:
            await self._fail_build(
                build_id=running.id,
                knowledge_base_id=knowledge_base.id,
                error_code="rag_index_unavailable",
                safe_message="The document index could not be completed.",
            )
            duration = max(perf_counter() - started_clock, 0.0)
            record_rag_index_processing(
                stage=processing_stage,
                final_status="failed",
                duration_seconds=duration,
            )
            record_rag_index_lifecycle(event="build_terminal", final_status="failed")
            raise RAGUnavailableError(
                "The document index could not be completed."
            ) from exc
        except Exception as exc:
            await self._fail_build(
                build_id=build_id,
                knowledge_base_id=knowledge_base.id,
                error_code="rag_index_unavailable",
                safe_message="The document index could not be completed.",
            )
            duration = max(perf_counter() - started_clock, 0.0)
            record_rag_index_processing(
                stage=processing_stage,
                final_status="failed",
                duration_seconds=duration,
            )
            record_rag_index_lifecycle(event="build_terminal", final_status="failed")
            raise RAGUnavailableError(
                "The document index could not be completed."
            ) from exc

        duration = max(perf_counter() - started_clock, 0.0)
        record_rag_index_processing(
            stage="indexing", final_status="succeeded", duration_seconds=duration
        )
        record_rag_index_lifecycle(event="build_terminal", final_status="succeeded")
        emit_safe(
            audit_logger,
            logging.INFO,
            "security_audit",
            extra={"audit_event": "rag_index_completed", "outcome": "success"},
        )
        return succeeded

    async def cancel_active_build(
        self, *, knowledge_base_id: UUID, user_id: UUID, is_admin: bool
    ) -> RAGIndexBuild:
        knowledge_base = await self._get_knowledge_base(
            knowledge_base_id=knowledge_base_id, user_id=user_id, is_admin=is_admin
        )
        active = await self._repository.latest_active_build(knowledge_base.id)
        if active is None:
            raise RAGConflictError("No cancellable index build is active.")
        cancelled_at = utc_now()
        cancelled = await self._repository.transition_build(
            build_id=active.id,
            expected_status=active.status,
            expected_version=active.state_version,
            new_status=RAGIndexBuildStatus.CANCELLED,
            values={"cancelled_at": cancelled_at, "finished_at": cancelled_at},
        )
        if cancelled is None:
            await self._repository.rollback()
            raise RAGConflictError("The index build changed concurrently.")
        restored_status = (
            RAGKnowledgeBaseStatus.READY
            if knowledge_base.active_index_build_id is not None
            else RAGKnowledgeBaseStatus.DRAFT
        )
        changed = await self._repository.update_knowledge_base(
            knowledge_base_id=knowledge_base.id,
            expected_version=knowledge_base.state_version,
            values={"status": restored_status, "updated_at": cancelled_at},
        )
        if changed is None:
            await self._repository.rollback()
            raise RAGConflictError("The knowledge base changed concurrently.")
        await self._repository.commit()
        record_rag_index_lifecycle(event="build_cancelled", final_status="cancelled")
        return cancelled

    async def reconcile_stale(
        self,
        *,
        queue: RAGIndexQueue,
        queued_before: datetime,
        running_before: datetime,
        limit: int = 100,
        maximum_enqueue_attempts: int = 3,
    ) -> RAGReconciliationResult:
        """Repair a bounded batch without replaying partially persisted work.

        A stale queued build can be safely re-enqueued because the worker claim is
        compare-and-swap. A stale running build is terminalized; it is never replayed
        over potentially partial work, and the owner may request a clean new build.
        """
        if not 1 <= limit <= 1000:
            raise RAGValidationError("The reconciliation batch limit is invalid.")
        if not 1 <= maximum_enqueue_attempts <= 100:
            raise RAGValidationError("The enqueue attempt limit is invalid.")
        stale = await self._repository.list_stale_active_builds(
            queued_before=queued_before,
            running_before=running_before,
            limit=limit,
        )
        requeued = 0
        failed_stale = 0
        enqueue_failures = 0
        for build in stale:
            if build.status is RAGIndexBuildStatus.QUEUED:
                if build.enqueue_attempt_count >= maximum_enqueue_attempts:
                    safe_message = (
                        "The document index could not be delivered"
                        " after bounded retries."
                    )
                    failed = await self._repository.fail_exhausted_queued_build(
                        build_id=build.id,
                        expected_version=build.state_version,
                        maximum_attempts=maximum_enqueue_attempts,
                        stale_before=queued_before,
                        error_code="rag_index_enqueue_retries_exhausted",
                        safe_error_message=safe_message,
                    )
                    if failed is None:
                        await self._repository.rollback()
                        continue
                    knowledge_base = await self._repository.get_knowledge_base(
                        knowledge_base_id=build.knowledge_base_id,
                        user_id=UUID(int=0),
                        is_admin=True,
                    )
                    if knowledge_base is None:
                        await self._repository.rollback()
                        continue
                    restored_status = (
                        RAGKnowledgeBaseStatus.READY
                        if knowledge_base.active_index_build_id is not None
                        else RAGKnowledgeBaseStatus.FAILED
                    )
                    changed = await self._repository.update_knowledge_base(
                        knowledge_base_id=knowledge_base.id,
                        expected_version=knowledge_base.state_version,
                        values={
                            "status": restored_status,
                            "error_code": "rag_index_enqueue_retries_exhausted",
                            "safe_error_message": safe_message,
                            "updated_at": utc_now(),
                        },
                    )
                    if changed is None:
                        await self._repository.rollback()
                        continue
                    await self._repository.commit()
                    failed_stale += 1
                    continue
                attempted = await self._repository.record_build_enqueue_attempt(
                    build_id=build.id,
                    expected_version=build.state_version,
                    maximum_attempts=maximum_enqueue_attempts,
                    stale_before=queued_before,
                )
                if attempted is None:
                    await self._repository.rollback()
                    continue
                await self._repository.commit()
                try:
                    queue.enqueue(attempted.id)
                except Exception:
                    enqueue_failures += 1
                    continue
                requeued += 1
                continue
            if await self._fail_build(
                build_id=build.id,
                knowledge_base_id=build.knowledge_base_id,
                error_code="rag_index_stale",
                safe_message="The document index worker did not complete in time.",
            ):
                failed_stale += 1
        repaired = requeued + failed_stale
        if repaired:
            record_reconciliation_repair(
                workload="rag_indexing", outcome="repaired", count=repaired
            )
        if enqueue_failures:
            record_reconciliation_repair(
                workload="rag_indexing",
                outcome="failed",
                count=enqueue_failures,
            )
        return RAGReconciliationResult(requeued, failed_stale, enqueue_failures)

    async def reconcile_stale_messages(
        self, *, before: datetime, limit: int = 100
    ) -> int:
        """Fail assistant messages interrupted after their durable acceptance."""
        if not 1 <= limit <= 1000:
            raise RAGValidationError("The reconciliation batch limit is invalid.")
        repaired = await self._repository.fail_stale_messages(
            before=before,
            limit=limit,
        )
        await self._repository.commit()
        if repaired:
            record_reconciliation_repair(
                workload="chat_generation",
                outcome="repaired",
                count=repaired,
            )
            emit_safe(
                audit_logger,
                logging.WARNING,
                "security_audit",
                extra={
                    "audit_event": "chatbot_stale_requests_reconciled",
                    "outcome": "failed_safe",
                },
            )
        return repaired

    async def list_builds(
        self,
        *,
        knowledge_base_id: UUID,
        user_id: UUID,
        is_admin: bool,
        limit: int,
        offset: int,
    ) -> EntityPage[RAGIndexBuild]:
        await self._get_knowledge_base(
            knowledge_base_id=knowledge_base_id, user_id=user_id, is_admin=is_admin
        )
        return await self._repository.list_builds(
            knowledge_base_id=knowledge_base_id, limit=limit, offset=offset
        )

    @traced_async_operation("rag.retrieval")
    async def search(
        self,
        *,
        knowledge_base_id: UUID,
        user_id: UUID,
        is_admin: bool,
        query: str,
        top_k: int,
        min_score: float,
    ) -> RetrievalResponse:
        started_clock = perf_counter()
        try:
            result = await self._search_authorized(
                knowledge_base_id=knowledge_base_id,
                user_id=user_id,
                is_admin=is_admin,
                query=query,
                top_k=top_k,
                min_score=min_score,
            )
        except Exception:
            record_rag_retrieval(
                final_status="failed",
                duration_seconds=max(perf_counter() - started_clock, 0.0),
                retrieved_chunks=0,
            )
            raise
        record_rag_retrieval(
            final_status=(
                "insufficient_evidence" if result.insufficient_evidence else "succeeded"
            ),
            duration_seconds=max(perf_counter() - started_clock, 0.0),
            retrieved_chunks=len(result.results),
        )
        return result

    async def _search_authorized(
        self,
        *,
        knowledge_base_id: UUID,
        user_id: UUID,
        is_admin: bool,
        query: str,
        top_k: int,
        min_score: float,
    ) -> RetrievalResponse:
        knowledge_base = await self._get_knowledge_base(
            knowledge_base_id=knowledge_base_id, user_id=user_id, is_admin=is_admin
        )
        if (
            knowledge_base.status is not RAGKnowledgeBaseStatus.READY
            or knowledge_base.active_index_build_id is None
        ):
            raise RAGConflictError("The knowledge base is not ready for retrieval.")
        query_vector = (await self._embed_texts((query,), workload="rag_retrieval"))[0]
        candidates = await self._repository.list_retrieval_candidates(
            knowledge_base_id=knowledge_base.id,
            active_build_id=knowledge_base.active_index_build_id,
            user_id=user_id,
            is_admin=is_admin,
            query_embedding=query_vector,
            top_k=top_k,
            min_score=min_score,
            maximum_candidates=_MAX_RETRIEVAL_CANDIDATES,
        )
        if len(candidates) > _MAX_RETRIEVAL_CANDIDATES:
            raise RAGUnavailableError("The knowledge base index exceeds safe limits.")
        ranked: list[tuple[float, str, StoredRetrievalCandidate]] = []
        for candidate in candidates:
            score = (
                cosine_similarity(query_vector, candidate.embedding.embedding)
                if candidate.score is None
                else max(0.0, min(1.0, candidate.score))
            )
            if score >= min_score:
                ranked.append((score, str(candidate.chunk.id), candidate))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        results: list[RetrievalResult] = []
        for rank, (score, _chunk_key, candidate) in enumerate(ranked[:top_k], start=1):
            excerpt = " ".join(candidate.chunk.content.split())[
                :_MAX_EXCERPT_CHARACTERS
            ]
            results.append(
                RetrievalResult(
                    chunk_id=candidate.chunk.id,
                    document_id=candidate.document.id,
                    dataset_version_id=candidate.chunk.dataset_version_id,
                    rank=rank,
                    score=score,
                    excerpt=excerpt,
                    document_title=candidate.document.title,
                    page_number=candidate.chunk.page_number,
                    section=candidate.chunk.section,
                )
            )
        return RetrievalResponse(
            knowledge_base_id=knowledge_base.id,
            results=tuple(results),
            insufficient_evidence=not results,
        )

    async def create_conversation(
        self,
        *,
        owner_user_id: UUID,
        is_admin: bool,
        knowledge_base_id: UUID,
        title: str | None,
    ) -> RAGConversation:
        knowledge_base = await self._get_knowledge_base(
            knowledge_base_id=knowledge_base_id,
            user_id=owner_user_id,
            is_admin=is_admin,
        )
        if knowledge_base.owner_user_id != owner_user_id:
            raise RAGNotFoundError("Knowledge base not found.")
        if knowledge_base.status is not RAGKnowledgeBaseStatus.READY:
            raise RAGConflictError("The knowledge base is not ready for chat.")
        entity = await self._repository.create_conversation(
            owner_user_id=owner_user_id,
            knowledge_base_id=knowledge_base_id,
            title=title or "New grounded conversation",
            status=RAGConversationStatus.ACTIVE,
        )
        await self._repository.commit()
        emit_safe(
            audit_logger,
            logging.INFO,
            "security_audit",
            extra={"audit_event": "rag_conversation_created", "outcome": "success"},
        )
        return entity

    async def get_conversation(
        self, *, conversation_id: UUID, user_id: UUID, is_admin: bool
    ) -> RAGConversation:
        entity = await self._repository.get_conversation(
            conversation_id=conversation_id, user_id=user_id, is_admin=is_admin
        )
        if entity is None:
            emit_safe(
                audit_logger,
                logging.WARNING,
                "security_audit",
                extra={
                    "audit_event": "rag_resource_access_denied",
                    "outcome": "denied",
                },
            )
            raise RAGNotFoundError("Conversation not found.")
        return entity

    async def list_conversations(
        self,
        *,
        user_id: UUID,
        is_admin: bool,
        status: RAGConversationStatus | None,
        limit: int,
        offset: int,
    ) -> EntityPage[RAGConversation]:
        return await self._repository.list_conversations(
            user_id=user_id,
            is_admin=is_admin,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def archive_conversation(
        self, *, conversation_id: UUID, user_id: UUID, is_admin: bool
    ) -> RAGConversation:
        conversation = await self.get_conversation(
            conversation_id=conversation_id, user_id=user_id, is_admin=is_admin
        )
        if conversation.status is RAGConversationStatus.ARCHIVED:
            return conversation
        archived = await self._repository.archive_conversation(
            conversation_id=conversation.id,
            expected_version=conversation.state_version,
            archived_at=utc_now(),
        )
        if archived is None:
            await self._repository.rollback()
            raise RAGConflictError("The conversation changed concurrently.")
        await self._repository.commit()
        return archived

    async def list_messages(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        is_admin: bool,
        limit: int,
        offset: int,
    ) -> EntityPage[RAGMessage]:
        await self.get_conversation(
            conversation_id=conversation_id, user_id=user_id, is_admin=is_admin
        )
        return await self._repository.list_messages(
            conversation_id=conversation_id, limit=limit, offset=offset
        )

    @traced_async_operation("chatbot.generation")
    async def submit_message(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        is_admin: bool,
        content: str,
        idempotency_key: str,
    ) -> MessageExchange:
        conversation = await self.get_conversation(
            conversation_id=conversation_id, user_id=user_id, is_admin=is_admin
        )
        if conversation.status is not RAGConversationStatus.ACTIVE:
            raise RAGConflictError("The conversation is archived.")
        normalized_content = content.strip()
        fingerprint = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
        existing = await self._repository.find_idempotent_user_message(
            conversation_id=conversation.id, idempotency_key=idempotency_key
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise RAGConflictError(
                    "The idempotency key was used for a different message."
                )
            reply = await self._repository.get_assistant_reply(existing.id)
            if reply is None:
                raise RAGConflictError("The existing message is still processing.")
            return MessageExchange(existing, reply)

        now = utc_now()
        try:
            user_message = await self._repository.create_message(
                conversation_id=conversation.id,
                role=RAGMessageRole.USER,
                content=normalized_content,
                character_count=len(normalized_content),
                status=RAGMessageStatus.SUCCEEDED,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                completed_at=now,
            )
            assistant = await self._repository.create_message(
                conversation_id=conversation.id,
                reply_to_message_id=user_message.id,
                role=RAGMessageRole.ASSISTANT,
                content="Answer generation is in progress.",
                character_count=0,
                status=RAGMessageStatus.RETRIEVING,
                generation_provider=self._generation.provider_name,
                generation_model=self._generation.model_name,
            )
            assistant_id = assistant.id
            await self._repository.commit()
            emit_safe(
                audit_logger,
                logging.INFO,
                "security_audit",
                extra={
                    "audit_event": "chatbot_request_accepted",
                    "outcome": "accepted",
                },
            )
        except IntegrityError as exc:
            await self._repository.rollback()
            concurrent = await self._repository.find_idempotent_user_message(
                conversation_id=conversation.id, idempotency_key=idempotency_key
            )
            if concurrent is None:
                raise RAGUnavailableError(
                    "The grounded message could not be persisted."
                ) from exc
            if concurrent.request_fingerprint != fingerprint:
                raise RAGConflictError(
                    "The idempotency key was used for a different message."
                ) from exc
            reply = await self._repository.get_assistant_reply(concurrent.id)
            if reply is None:
                raise RAGConflictError(
                    "The existing message is still processing."
                ) from exc
            return MessageExchange(concurrent, reply)

        generation_started = perf_counter()
        try:
            retrieval = await self.search(
                knowledge_base_id=conversation.knowledge_base_id,
                user_id=user_id,
                is_admin=is_admin,
                query=normalized_content,
                top_k=5,
                min_score=0.05,
            )
            transitioned = await self._repository.transition_message(
                message_id=assistant.id,
                expected_status=RAGMessageStatus.RETRIEVING,
                new_status=RAGMessageStatus.GENERATING,
                values={},
            )
            if transitioned is None:
                raise RAGConflictError("The grounded message is no longer active.")
            assistant = transitioned
            await self._repository.commit()
            recent_history = await self._repository.recent_succeeded_message_content(
                conversation_id=conversation.id, limit=_MAX_RECENT_MESSAGES
            )
            answer = await self._generate_answer(
                question=normalized_content,
                evidence=retrieval.results,
                recent_history=recent_history,
            )
            self._validate_grounded_answer(answer)
            allowed = {item.rank: item for item in retrieval.results}
            cited = tuple(
                allowed[rank] for rank in answer.cited_ranks if rank in allowed
            )
            if answer.cited_ranks and len(cited) != len(answer.cited_ranks):
                raise RAGUnavailableError("Answer citation validation failed.")
            completed_at = utc_now()
            completed = await self._repository.transition_message(
                message_id=assistant.id,
                expected_status=RAGMessageStatus.GENERATING,
                new_status=RAGMessageStatus.SUCCEEDED,
                values={
                    "content": answer.content,
                    "character_count": len(answer.content),
                    "grounded_outcome": answer.outcome,
                    "completed_at": completed_at,
                    "error_code": None,
                    "safe_error_message": None,
                },
            )
            if completed is None:
                raise RAGConflictError("The grounded message is no longer active.")
            assistant = completed
            await self._repository.add_citations(
                message_id=assistant.id,
                citations=tuple(
                    {
                        "chunk_id": item.chunk_id,
                        "document_id": item.document_id,
                        "dataset_version_id": item.dataset_version_id,
                        "rank": item.rank,
                        "score": item.score,
                        "excerpt": item.excerpt,
                        "document_title": item.document_title,
                        "page_number": item.page_number,
                        "section": item.section,
                    }
                    for item in cited
                ),
            )
            refreshed_conversation = await self.get_conversation(
                conversation_id=conversation.id, user_id=user_id, is_admin=is_admin
            )
            await self._repository.touch_conversation(
                conversation_id=conversation.id,
                expected_version=refreshed_conversation.state_version,
                updated_at=completed_at,
            )
            await self._repository.commit()
        except Exception as exc:
            await self._repository.rollback()
            await self._repository.fail_active_message(
                message_id=assistant_id,
                values={
                    "content": "The grounded answer could not be completed.",
                    "character_count": len(
                        "The grounded answer could not be completed."
                    ),
                    "completed_at": utc_now(),
                    "error_code": "rag_generation_failed",
                    "safe_error_message": "The grounded answer could not be completed.",
                },
            )
            await self._repository.commit()
            emit_safe(
                audit_logger,
                logging.WARNING,
                "security_audit",
                extra={"audit_event": "rag_message_completed", "outcome": "failure"},
            )
            record_chatbot_generation(
                outcome="failed",
                duration_seconds=max(perf_counter() - generation_started, 0.0),
            )
            raise RAGUnavailableError(
                "The grounded answer could not be completed."
            ) from exc

        loaded_assistant = await self._repository.get_assistant_reply(user_message.id)
        if loaded_assistant is None:
            record_chatbot_generation(
                outcome="failed",
                duration_seconds=max(perf_counter() - generation_started, 0.0),
            )
            raise RAGUnavailableError("The grounded answer could not be loaded.")
        record_chatbot_generation(
            outcome=answer.outcome.value,
            duration_seconds=max(perf_counter() - generation_started, 0.0),
        )
        emit_safe(
            audit_logger,
            logging.INFO,
            "security_audit",
            extra={"audit_event": "rag_message_completed", "outcome": "success"},
        )
        return MessageExchange(user_message, loaded_assistant)

    async def cancel_message(
        self, *, message_id: UUID, user_id: UUID, is_admin: bool
    ) -> RAGMessage:
        message = await self._repository.get_message(
            message_id=message_id, user_id=user_id, is_admin=is_admin
        )
        if message is None:
            emit_safe(
                audit_logger,
                logging.WARNING,
                "security_audit",
                extra={
                    "audit_event": "rag_resource_access_denied",
                    "outcome": "denied",
                },
            )
            raise RAGNotFoundError("Message not found.")
        cancelled = await self._repository.cancel_message(
            message_id=message.id, completed_at=utc_now()
        )
        if cancelled is None:
            await self._repository.rollback()
            raise RAGConflictError("The message is already terminal.")
        await self._repository.commit()
        return cancelled

    async def archive_knowledge_base(
        self, *, knowledge_base_id: UUID, user_id: UUID, is_admin: bool
    ) -> KnowledgeBaseDetail:
        knowledge_base = await self._get_knowledge_base(
            knowledge_base_id=knowledge_base_id, user_id=user_id, is_admin=is_admin
        )
        if knowledge_base.status is RAGKnowledgeBaseStatus.ARCHIVED:
            return await self._detail(knowledge_base)
        if await self._repository.latest_active_build(knowledge_base.id) is not None:
            raise RAGConflictError("An active index build must finish before archival.")
        archived = await self._repository.update_knowledge_base(
            knowledge_base_id=knowledge_base.id,
            expected_version=knowledge_base.state_version,
            values={
                "status": RAGKnowledgeBaseStatus.ARCHIVED,
                "archived_at": utc_now(),
                "updated_at": utc_now(),
            },
        )
        if archived is None:
            await self._repository.rollback()
            raise RAGConflictError("The knowledge base changed concurrently.")
        await self._repository.commit()
        emit_safe(
            audit_logger,
            logging.INFO,
            "security_audit",
            extra={
                "audit_event": "rag_knowledge_base_archived",
                "outcome": "success",
            },
        )
        return await self._detail(archived)

    async def _get_knowledge_base(
        self, *, knowledge_base_id: UUID, user_id: UUID, is_admin: bool
    ) -> RAGKnowledgeBase:
        entity = await self._repository.get_knowledge_base(
            knowledge_base_id=knowledge_base_id, user_id=user_id, is_admin=is_admin
        )
        if entity is None:
            emit_safe(
                audit_logger,
                logging.WARNING,
                "security_audit",
                extra={
                    "audit_event": "rag_resource_access_denied",
                    "outcome": "denied",
                },
            )
            raise RAGNotFoundError("Knowledge base not found.")
        return entity

    async def _detail(self, entity: RAGKnowledgeBase) -> KnowledgeBaseDetail:
        attachments = await self._repository.list_attachments(entity.id)
        document_count = 0
        chunk_count = 0
        if entity.active_index_build_id is not None:
            build = await self._repository.get_build_internal(
                entity.active_index_build_id
            )
            if build is not None and build.status is RAGIndexBuildStatus.SUCCEEDED:
                document_count = build.indexed_document_count
                chunk_count = build.indexed_chunk_count
        return KnowledgeBaseDetail(
            knowledge_base=entity,
            attachments=attachments,
            indexed_document_count=document_count,
            indexed_chunk_count=chunk_count,
        )

    @staticmethod
    def _require_mutable_knowledge_base(entity: RAGKnowledgeBase) -> None:
        if entity.status is RAGKnowledgeBaseStatus.ARCHIVED:
            raise RAGConflictError("The knowledge base is archived.")
        if entity.status is RAGKnowledgeBaseStatus.INDEXING:
            raise RAGConflictError("The knowledge base is currently indexing.")

    @staticmethod
    def _chunking_configuration(entity: RAGKnowledgeBase) -> tuple[int, int, int]:
        configuration = entity.chunking_configuration
        try:
            chunk_size = _configuration_integer(configuration["chunk_size"])
            overlap = _configuration_integer(configuration["chunk_overlap"])
            maximum = _configuration_integer(configuration["maximum_chunks"])
        except (KeyError, RAGValidationError) as exc:
            raise RAGValidationError(
                "The knowledge-base chunking configuration is invalid."
            ) from exc
        return chunk_size, overlap, maximum

    async def _chunk_document(
        self,
        *,
        text: str,
        chunk_size: int,
        overlap: int,
        maximum_chunks: int,
    ) -> tuple[TextChunk, ...]:
        try:
            with fail_after(_LOCAL_OPERATION_TIMEOUT_SECONDS):
                return await to_thread.run_sync(
                    lambda: chunk_text(
                        text,
                        chunk_size=chunk_size,
                        overlap=overlap,
                        maximum_chunks=maximum_chunks,
                    ),
                    abandon_on_cancel=True,
                )
        except TimeoutError as exc:
            record_process_timeout(workload="document_chunking")
            raise RAGUnavailableError(
                "Document chunking did not complete in time."
            ) from exc

    async def _embed_chunks(
        self, texts: tuple[str, ...]
    ) -> tuple[tuple[float, ...], ...]:
        result: list[tuple[float, ...]] = []
        for start in range(0, len(texts), _EMBEDDING_BATCH_SIZE):
            result.extend(
                await self._embed_texts(
                    texts[start : start + _EMBEDDING_BATCH_SIZE],
                    workload="rag_indexing",
                )
            )
        return tuple(result)

    async def _embed_texts(
        self, texts: tuple[str, ...], *, workload: str
    ) -> tuple[tuple[float, ...], ...]:
        try:
            with fail_after(_LOCAL_OPERATION_TIMEOUT_SECONDS):
                vectors = await to_thread.run_sync(
                    lambda: self._embedding.embed(texts),
                    abandon_on_cancel=True,
                )
        except TimeoutError as exc:
            record_process_timeout(workload=workload)
            raise RAGUnavailableError(
                "The embedding provider did not complete in time."
            ) from exc
        except EmbeddingInputError as exc:
            if workload == "rag_retrieval":
                raise RAGValidationError(
                    "The retrieval query contains no indexable terms."
                ) from exc
            raise EmbeddingInputError(
                "The embedding provider rejected bounded input."
            ) from exc
        if len(vectors) != len(texts):
            raise EmbeddingInputError("The embedding provider returned invalid output.")
        validated: list[tuple[float, ...]] = []
        for vector in vectors:
            if len(vector) != self._embedding.dimension or not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in vector
            ):
                raise EmbeddingInputError(
                    "The embedding provider returned invalid output."
                )
            validated.append(tuple(float(value) for value in vector))
        return tuple(validated)

    async def _generate_answer(
        self,
        *,
        question: str,
        evidence: tuple[RetrievalResult, ...],
        recent_history: tuple[str, ...],
    ) -> GroundedAnswer:
        try:
            with fail_after(_LOCAL_OPERATION_TIMEOUT_SECONDS):
                return await to_thread.run_sync(
                    lambda: self._generation.generate(
                        question=question,
                        evidence=evidence,
                        recent_history=recent_history,
                    ),
                    abandon_on_cancel=True,
                )
        except TimeoutError as exc:
            record_process_timeout(workload="chatbot_generation")
            raise RAGUnavailableError(
                "The grounded answer did not complete in time."
            ) from exc

    @staticmethod
    def _validate_grounded_answer(answer: GroundedAnswer) -> None:
        if not answer.content.strip() or len(answer.content) > 4000:
            raise RAGUnavailableError("Answer validation failed.")
        if len(set(answer.cited_ranks)) != len(answer.cited_ranks):
            raise RAGUnavailableError("Answer citation validation failed.")
        if (answer.outcome is GroundedOutcome.GROUNDED and not answer.cited_ranks) or (
            answer.outcome is GroundedOutcome.INSUFFICIENT_EVIDENCE
            and answer.cited_ranks
        ):
            raise RAGUnavailableError("Answer grounding validation failed.")

    async def _fail_build(
        self,
        *,
        build_id: UUID,
        knowledge_base_id: UUID,
        error_code: str,
        safe_message: str,
    ) -> bool:
        await self._repository.rollback()
        build = await self._repository.get_build_internal(build_id)
        knowledge_base = await self._repository.get_knowledge_base(
            knowledge_base_id=knowledge_base_id,
            user_id=UUID(int=0),
            is_admin=True,
        )
        if build is None or knowledge_base is None:
            return False
        if build.status not in (
            RAGIndexBuildStatus.QUEUED,
            RAGIndexBuildStatus.RUNNING,
        ):
            return False
        failed_at = utc_now()
        failed = await self._repository.transition_build(
            build_id=build.id,
            expected_status=build.status,
            expected_version=build.state_version,
            new_status=RAGIndexBuildStatus.FAILED,
            values={
                "finished_at": failed_at,
                "error_code": error_code,
                "safe_error_message": safe_message,
            },
        )
        if failed is None:
            await self._repository.rollback()
            return False
        restored_status = (
            RAGKnowledgeBaseStatus.READY
            if knowledge_base.active_index_build_id is not None
            else RAGKnowledgeBaseStatus.FAILED
        )
        changed = await self._repository.update_knowledge_base(
            knowledge_base_id=knowledge_base.id,
            expected_version=knowledge_base.state_version,
            values={
                "status": restored_status,
                "error_code": error_code,
                "safe_error_message": safe_message,
                "updated_at": failed_at,
            },
        )
        if changed is None:
            await self._repository.rollback()
            return False
        await self._repository.commit()
        emit_safe(
            audit_logger,
            logging.WARNING,
            "security_audit",
            extra={"audit_event": "rag_index_completed", "outcome": "failure"},
        )
        return True


def _configuration_integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RAGValidationError(
            "The knowledge-base chunking configuration is invalid."
        )
    return value
