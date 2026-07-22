"""Authorized registered-document retrieval and grounded chat routes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import require_roles
from app.dependencies.database import get_db_session
from app.dependencies.operational import require_training_worker_available
from app.dependencies.rate_limit import enforce_mutation_rate_limit
from app.models.rag import (
    RAGConversation,
    RAGIndexBuild,
    RAGMessage,
    RAGMessageCitation,
)
from app.models.user import User, UserRole
from app.rag.domain import RAGConversationStatus, RAGKnowledgeBaseStatus
from app.rag.queue import RAGIndexQueue, get_rag_index_queue
from app.repositories.rag import RAGRepository
from app.schemas.rag import (
    ConversationCreateRequest,
    ConversationPageResponse,
    ConversationResponse,
    DatasetVersionAttachmentRequest,
    DatasetVersionAttachmentResponse,
    IndexBuildPageResponse,
    IndexBuildResponse,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseDetailResponse,
    KnowledgeBasePageResponse,
    KnowledgeBaseSummaryResponse,
    MessageCitationResponse,
    MessageExchangeResponse,
    MessagePageResponse,
    MessageResponse,
    MessageSubmitRequest,
    RetrievalResultResponse,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
)
from app.services.rag import (
    KnowledgeBaseDetail,
    RAGConflictError,
    RAGNotFoundError,
    RAGService,
    RAGServiceError,
    RAGUnavailableError,
    RAGValidationError,
)

router = APIRouter()
rag_router = APIRouter(prefix="/ai/rag", tags=["rag"])
chat_router = APIRouter(prefix="/ai/chat", tags=["chat"])

AuthorizedUser = Annotated[
    User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
]
Session = Annotated[AsyncSession, Depends(get_db_session)]
IndexQueue = Annotated[RAGIndexQueue, Depends(get_rag_index_queue)]


def _service(session: AsyncSession) -> RAGService:
    return RAGService(RAGRepository(session))


def _http_error(exc: RAGServiceError) -> HTTPException:
    if isinstance(exc, RAGNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, RAGConflictError):
        code = status.HTTP_409_CONFLICT
    elif isinstance(exc, RAGValidationError):
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif isinstance(exc, RAGUnavailableError):
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        code = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail = (
        str(exc)
        if code != status.HTTP_500_INTERNAL_SERVER_ERROR
        else "The request could not be completed."
    )
    return HTTPException(status_code=code, detail=detail)


@rag_router.get(
    "/knowledge-bases",
    response_model=KnowledgeBasePageResponse,
    summary="List authorized knowledge bases",
)
async def list_knowledge_bases(
    current_user: AuthorizedUser,
    session: Session,
    status_filter: Annotated[
        RAGKnowledgeBaseStatus | None, Query(alias="status")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> KnowledgeBasePageResponse:
    page = await _service(session).list_knowledge_bases(
        user_id=current_user.id,
        is_admin=current_user.role is UserRole.ADMIN,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return KnowledgeBasePageResponse(
        items=[_knowledge_base_summary(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@rag_router.post(
    "/knowledge-bases",
    response_model=KnowledgeBaseDetailResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
    summary="Create a local registered-document knowledge base",
)
async def create_knowledge_base(
    payload: KnowledgeBaseCreateRequest,
    current_user: AuthorizedUser,
    session: Session,
) -> KnowledgeBaseDetailResponse:
    try:
        detail = await _service(session).create_knowledge_base(
            owner_user_id=current_user.id,
            name=payload.name,
            description=payload.description,
            chunk_size=payload.chunk_size,
            chunk_overlap=payload.chunk_overlap,
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return _knowledge_base_detail(detail)


@rag_router.get(
    "/knowledge-bases/{knowledge_base_id}",
    response_model=KnowledgeBaseDetailResponse,
    summary="Get one authorized knowledge base",
)
async def get_knowledge_base(
    knowledge_base_id: UUID,
    current_user: AuthorizedUser,
    session: Session,
) -> KnowledgeBaseDetailResponse:
    try:
        detail = await _service(session).get_knowledge_base_detail(
            knowledge_base_id=knowledge_base_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return _knowledge_base_detail(detail)


@rag_router.post(
    "/knowledge-bases/{knowledge_base_id}/archive",
    response_model=KnowledgeBaseDetailResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
    summary="Archive a knowledge base",
)
async def archive_knowledge_base(
    knowledge_base_id: UUID,
    current_user: AuthorizedUser,
    session: Session,
) -> KnowledgeBaseDetailResponse:
    try:
        detail = await _service(session).archive_knowledge_base(
            knowledge_base_id=knowledge_base_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return _knowledge_base_detail(detail)


@rag_router.post(
    "/knowledge-bases/{knowledge_base_id}/dataset-versions",
    response_model=DatasetVersionAttachmentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
    summary="Attach an authorized ready document dataset version",
)
async def attach_dataset_version(
    knowledge_base_id: UUID,
    payload: DatasetVersionAttachmentRequest,
    current_user: AuthorizedUser,
    session: Session,
) -> DatasetVersionAttachmentResponse:
    try:
        attachment = await _service(session).attach_dataset_version(
            knowledge_base_id=knowledge_base_id,
            dataset_version_id=payload.dataset_version_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return DatasetVersionAttachmentResponse.model_validate(attachment)


@rag_router.delete(
    "/knowledge-bases/{knowledge_base_id}/dataset-versions/{dataset_version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(enforce_mutation_rate_limit)],
    summary="Detach a document dataset version",
)
async def detach_dataset_version(
    knowledge_base_id: UUID,
    dataset_version_id: UUID,
    current_user: AuthorizedUser,
    session: Session,
) -> Response:
    try:
        await _service(session).detach_dataset_version(
            knowledge_base_id=knowledge_base_id,
            dataset_version_id=dataset_version_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@rag_router.post(
    "/knowledge-bases/{knowledge_base_id}/build",
    response_model=IndexBuildResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(enforce_mutation_rate_limit),
        Depends(require_training_worker_available),
    ],
    summary="Queue a bounded local document index build",
)
async def build_index(
    knowledge_base_id: UUID,
    current_user: AuthorizedUser,
    session: Session,
    queue: IndexQueue,
) -> IndexBuildResponse:
    try:
        build = await _service(session).create_and_enqueue_build(
            knowledge_base_id=knowledge_base_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
            queue=queue,
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return _build_response(build)


@rag_router.post(
    "/knowledge-bases/{knowledge_base_id}/cancel-build",
    response_model=IndexBuildResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
    summary="Cancel a queued or running index build",
)
async def cancel_index_build(
    knowledge_base_id: UUID,
    current_user: AuthorizedUser,
    session: Session,
) -> IndexBuildResponse:
    try:
        build = await _service(session).cancel_active_build(
            knowledge_base_id=knowledge_base_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return _build_response(build)


@rag_router.get(
    "/knowledge-bases/{knowledge_base_id}/builds",
    response_model=IndexBuildPageResponse,
    summary="List authorized index builds",
)
async def list_index_builds(
    knowledge_base_id: UUID,
    current_user: AuthorizedUser,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> IndexBuildPageResponse:
    try:
        page = await _service(session).list_builds(
            knowledge_base_id=knowledge_base_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
            limit=limit,
            offset=offset,
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return IndexBuildPageResponse(
        items=[_build_response(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@rag_router.post(
    "/knowledge-bases/{knowledge_base_id}/search",
    response_model=RetrievalSearchResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
    summary="Search only authorized registered document chunks",
)
async def search_knowledge_base(
    knowledge_base_id: UUID,
    payload: RetrievalSearchRequest,
    current_user: AuthorizedUser,
    session: Session,
) -> RetrievalSearchResponse:
    try:
        result = await _service(session).search(
            knowledge_base_id=knowledge_base_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
            query=payload.query,
            top_k=payload.top_k,
            min_score=float(payload.min_score),
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return RetrievalSearchResponse(
        knowledge_base_id=result.knowledge_base_id,
        results=[
            RetrievalResultResponse(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                dataset_version_id=item.dataset_version_id,
                rank=item.rank,
                score=item.score,
                excerpt=item.excerpt,
                document_title=item.document_title,
                page_number=item.page_number,
                section=item.section,
            )
            for item in result.results
        ],
        insufficient_evidence=result.insufficient_evidence,
    )


@chat_router.get(
    "/conversations",
    response_model=ConversationPageResponse,
    summary="List authorized grounded conversations",
)
async def list_conversations(
    current_user: AuthorizedUser,
    session: Session,
    status_filter: Annotated[
        RAGConversationStatus | None, Query(alias="status")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> ConversationPageResponse:
    page = await _service(session).list_conversations(
        user_id=current_user.id,
        is_admin=current_user.role is UserRole.ADMIN,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return ConversationPageResponse(
        items=[_conversation_response(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@chat_router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
    summary="Create a grounded conversation",
)
async def create_conversation(
    payload: ConversationCreateRequest,
    current_user: AuthorizedUser,
    session: Session,
) -> ConversationResponse:
    try:
        entity = await _service(session).create_conversation(
            owner_user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
            knowledge_base_id=payload.knowledge_base_id,
            title=payload.title,
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return _conversation_response(entity)


@chat_router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    summary="Get one grounded conversation",
)
async def get_conversation(
    conversation_id: UUID,
    current_user: AuthorizedUser,
    session: Session,
) -> ConversationResponse:
    try:
        entity = await _service(session).get_conversation(
            conversation_id=conversation_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return _conversation_response(entity)


@chat_router.post(
    "/conversations/{conversation_id}/archive",
    response_model=ConversationResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
    summary="Archive a grounded conversation",
)
async def archive_conversation(
    conversation_id: UUID,
    current_user: AuthorizedUser,
    session: Session,
) -> ConversationResponse:
    try:
        entity = await _service(session).archive_conversation(
            conversation_id=conversation_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return _conversation_response(entity)


@chat_router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessagePageResponse,
    summary="List bounded grounded conversation messages",
)
async def list_messages(
    conversation_id: UUID,
    current_user: AuthorizedUser,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> MessagePageResponse:
    try:
        page = await _service(session).list_messages(
            conversation_id=conversation_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
            limit=limit,
            offset=offset,
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return MessagePageResponse(
        items=[_message_response(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@chat_router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageExchangeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
    summary="Submit a bounded grounded message",
)
async def submit_message(
    conversation_id: UUID,
    payload: MessageSubmitRequest,
    current_user: AuthorizedUser,
    session: Session,
) -> MessageExchangeResponse:
    try:
        result = await _service(session).submit_message(
            conversation_id=conversation_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
            content=payload.content,
            idempotency_key=payload.idempotency_key,
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return MessageExchangeResponse(
        user_message=_message_response(result.user_message),
        assistant_message=_message_response(result.assistant_message),
    )


@chat_router.post(
    "/messages/{message_id}/cancel",
    response_model=MessageResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
    summary="Cancel a nonterminal grounded message",
)
async def cancel_message(
    message_id: UUID,
    current_user: AuthorizedUser,
    session: Session,
) -> MessageResponse:
    try:
        entity = await _service(session).cancel_message(
            message_id=message_id,
            user_id=current_user.id,
            is_admin=current_user.role is UserRole.ADMIN,
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return _message_response(entity)


def _knowledge_base_summary(
    value: KnowledgeBaseDetail,
) -> KnowledgeBaseSummaryResponse:
    entity = value.knowledge_base
    return KnowledgeBaseSummaryResponse(
        knowledge_base_id=entity.id,
        name=entity.name,
        description=entity.description,
        status=entity.status,
        embedding_provider=entity.embedding_provider,
        embedding_model=entity.embedding_model,
        embedding_dimension=entity.embedding_dimension,
        attached_dataset_version_count=len(value.attachments),
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _knowledge_base_detail(value: KnowledgeBaseDetail) -> KnowledgeBaseDetailResponse:
    entity = value.knowledge_base
    return KnowledgeBaseDetailResponse(
        **_knowledge_base_summary(value).model_dump(),
        chunking_configuration=entity.chunking_configuration,
        active_index_build_id=entity.active_index_build_id,
        indexed_document_count=value.indexed_document_count,
        indexed_chunk_count=value.indexed_chunk_count,
        dataset_versions=[
            DatasetVersionAttachmentResponse.model_validate(item)
            for item in value.attachments
        ],
        error_code=entity.error_code,
        safe_error_message=entity.safe_error_message,
        archived_at=entity.archived_at,
    )


def _build_response(value: RAGIndexBuild) -> IndexBuildResponse:
    return IndexBuildResponse(
        index_build_id=value.id,
        knowledge_base_id=value.knowledge_base_id,
        status=value.status,
        indexed_document_count=value.indexed_document_count,
        indexed_chunk_count=value.indexed_chunk_count,
        embedding_count=value.embedding_count,
        created_at=value.created_at,
        started_at=value.started_at,
        finished_at=value.finished_at,
        cancelled_at=value.cancelled_at,
        error_code=value.error_code,
        safe_error_message=value.safe_error_message,
    )


def _conversation_response(value: RAGConversation) -> ConversationResponse:
    return ConversationResponse(
        conversation_id=value.id,
        knowledge_base_id=value.knowledge_base_id,
        title=value.title,
        status=value.status,
        created_at=value.created_at,
        updated_at=value.updated_at,
        archived_at=value.archived_at,
    )


def _message_response(value: RAGMessage) -> MessageResponse:
    citations = value.__dict__.get("citations", ())
    if not isinstance(citations, Sequence):
        citations = ()
    return MessageResponse(
        message_id=value.id,
        conversation_id=value.conversation_id,
        reply_to_message_id=value.reply_to_message_id,
        role=value.role,
        content=value.content,
        status=value.status,
        grounded_outcome=value.grounded_outcome,
        generation_provider=value.generation_provider,
        generation_model=value.generation_model,
        citations=[
            _citation_response(item)
            for item in citations
            if isinstance(item, RAGMessageCitation)
        ],
        created_at=value.created_at,
        completed_at=value.completed_at,
        error_code=value.error_code,
        safe_error_message=value.safe_error_message,
    )


def _citation_response(value: RAGMessageCitation) -> MessageCitationResponse:
    return MessageCitationResponse(
        citation_id=value.id,
        chunk_id=value.chunk_id,
        document_id=value.document_id,
        dataset_version_id=value.dataset_version_id,
        rank=value.rank,
        score=value.score,
        excerpt=value.excerpt,
        document_title=value.document_title,
        page_number=value.page_number,
        section=value.section,
    )


router.include_router(rag_router)
router.include_router(chat_router)
