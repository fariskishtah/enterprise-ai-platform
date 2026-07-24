"""Guided CSV onboarding and AI readiness routes."""

from __future__ import annotations

import csv
import io
import json
from typing import Annotated, cast
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.dependencies.auth import require_roles
from app.dependencies.database import get_db_session
from app.dependencies.datasets import get_dataset_storage
from app.dependencies.rate_limit import enforce_mutation_rate_limit
from app.dependencies.services import get_audit_service
from app.models.user import User, UserRole
from app.schemas.demo_experience import (
    ConfirmImportRequest,
    DataImportResponse,
    GuidedTemplateResponse,
    GuidedUseCase,
    ImportListResponse,
    ImportMappingRequest,
    ReadinessRequest,
    ReadinessResponse,
    TrainingProfile,
)
from app.services.audit import AuditService
from app.services.guided_data import GuidedDataError, GuidedDataService

router = APIRouter(prefix="/data-onboarding", tags=["data-onboarding"])


def _service(session: AsyncSession, settings: Settings) -> GuidedDataService:
    return GuidedDataService(
        session=session,
        storage=get_dataset_storage(settings.dataset_storage_root),
        maximum_bytes=settings.dataset_upload_max_bytes,
        maximum_rows=settings.dataset_max_rows,
    )


def _error(exc: GuidedDataError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND
        if "not found" in str(exc).lower()
        else status.HTTP_409_CONFLICT
    )
    return HTTPException(code, str(exc))


@router.post(
    "/imports",
    response_model=DataImportResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def upload_import(
    file: Annotated[UploadFile, File(description="UTF-8 CSV file")],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> DataImportResponse:
    try:
        item = await _service(session, settings).create(
            company_id=user.company_id,
            user_id=user.id,
            filename=file.filename,
            media_type=file.content_type,
            idempotency_key=idempotency_key,
            source=file.file,
        )
    except GuidedDataError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await audit.record(
        company_id=user.company_id,
        actor=user,
        action="data_import.uploaded",
        resource_type="data_import",
        resource_id=item.id,
        result="success",
        metadata={"size_bytes": item.size_bytes, "rows": item.total_rows},
    )
    return DataImportResponse.model_validate(item)


@router.get("/imports", response_model=ImportListResponse)
async def list_imports(
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> ImportListResponse:
    items, total = await _service(session, settings).list_imports(
        company_id=user.company_id, limit=limit, offset=offset
    )
    return ImportListResponse(
        items=[DataImportResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/imports/{import_id}", response_model=DataImportResponse)
async def get_import(
    import_id: UUID,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DataImportResponse:
    try:
        item = await _service(session, settings).get(
            company_id=user.company_id, import_id=import_id
        )
    except GuidedDataError as exc:
        raise _error(exc) from exc
    return DataImportResponse.model_validate(item)


@router.put(
    "/imports/{import_id}/mapping",
    response_model=DataImportResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def set_import_mapping(
    import_id: UUID,
    payload: ImportMappingRequest,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DataImportResponse:
    try:
        item = await _service(session, settings).set_mapping(
            company_id=user.company_id,
            import_id=import_id,
            mapping=payload.mapping,
            delimiter=payload.delimiter,
        )
    except GuidedDataError as exc:
        raise _error(exc) from exc
    return DataImportResponse.model_validate(item)


@router.post(
    "/imports/{import_id}/validate",
    response_model=DataImportResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def validate_import(
    import_id: UUID,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> DataImportResponse:
    try:
        item = await _service(session, settings).validate(
            company_id=user.company_id, import_id=import_id
        )
    except GuidedDataError as exc:
        raise _error(exc) from exc
    await audit.record(
        company_id=user.company_id,
        actor=user,
        action="data_import.validated",
        resource_type="data_import",
        resource_id=item.id,
        result="success",
        metadata={
            "blocking_issues": item.quality_report.get("blocking_issue_count", 0),
            "warnings": item.quality_report.get("warning_issue_count", 0),
        },
    )
    return DataImportResponse.model_validate(item)


@router.post(
    "/imports/{import_id}/confirm",
    response_model=DataImportResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def confirm_import(
    import_id: UUID,
    payload: ConfirmImportRequest,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> DataImportResponse:
    try:
        item = await _service(session, settings).confirm(
            company_id=user.company_id,
            import_id=import_id,
            accept_warnings=payload.accept_warnings,
        )
    except GuidedDataError as exc:
        raise _error(exc) from exc
    await audit.record(
        company_id=user.company_id,
        actor=user,
        action="data_import.completed",
        resource_type="data_import",
        resource_id=item.id,
        result="success",
        metadata={"status": item.status, "imported_rows": item.imported_rows},
    )
    return DataImportResponse.model_validate(item)


@router.post(
    "/imports/{import_id}/cancel",
    response_model=DataImportResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def cancel_import(
    import_id: UUID,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DataImportResponse:
    try:
        item = await _service(session, settings).cancel(
            company_id=user.company_id, import_id=import_id
        )
    except GuidedDataError as exc:
        raise _error(exc) from exc
    return DataImportResponse.model_validate(item)


@router.get("/imports/{import_id}/quality.{format}")
async def export_quality(
    import_id: UUID,
    format: str,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    try:
        item = await _service(session, settings).get(
            company_id=user.company_id, import_id=import_id
        )
    except GuidedDataError as exc:
        raise _error(exc) from exc
    if format == "json":
        return Response(
            json.dumps(item.quality_report, separators=(",", ":")),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="quality-{item.id}.json"'
            },
        )
    if format != "csv":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export format not found.")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["severity", "code", "count", "meaning", "recommended_correction"])
    issues = item.quality_report.get("issues", [])
    if isinstance(issues, list):
        for issue in issues:
            if isinstance(issue, dict):
                writer.writerow(
                    [
                        issue.get("severity", ""),
                        issue.get("code", ""),
                        issue.get("count", 0),
                        issue.get("meaning", ""),
                        issue.get("correction", ""),
                    ]
                )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="quality-{item.id}.csv"'
        },
    )


@router.get("/guided-ai/templates", response_model=list[GuidedTemplateResponse])
async def guided_templates(
    _user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
) -> list[GuidedTemplateResponse]:
    profiles = list(TrainingProfile)
    return [
        GuidedTemplateResponse(
            use_case=GuidedUseCase.PREDICTIVE_MAINTENANCE,
            label="Predictive maintenance",
            task_type="classification",
            supported_profiles=profiles,
        ),
        GuidedTemplateResponse(
            use_case=GuidedUseCase.ENERGY_MONITORING,
            label="Energy monitoring",
            task_type="regression",
            supported_profiles=profiles,
        ),
        GuidedTemplateResponse(
            use_case=GuidedUseCase.QUALITY_PREDICTION,
            label="Quality prediction",
            task_type="classification",
            supported_profiles=profiles,
        ),
        GuidedTemplateResponse(
            use_case=GuidedUseCase.CONDITION_MONITORING,
            label="Condition monitoring",
            task_type="classification",
            supported_profiles=profiles,
        ),
    ]


@router.post("/guided-ai/readiness", response_model=ReadinessResponse)
async def guided_readiness(
    payload: ReadinessRequest,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReadinessResponse:
    try:
        item = await _service(session, settings).get(
            company_id=user.company_id, import_id=payload.import_id
        )
    except GuidedDataError as exc:
        raise _error(exc) from exc
    raw_headers = item.mapping.get("headers", [])
    headers = (
        [str(value) for value in raw_headers] if isinstance(raw_headers, list) else []
    )
    missing_features = [
        feature for feature in payload.features if feature not in headers
    ]
    target_available = payload.target is None or payload.target in headers
    raw_issues = item.quality_report.get("issues", [])
    issues = cast(list[object], raw_issues) if isinstance(raw_issues, list) else []
    blocking = [
        str(issue.get("code"))
        for issue in issues
        if isinstance(issue, dict) and issue.get("severity") == "Blocking"
    ]
    if missing_features:
        blocking.append("selected_features_unavailable")
    if not target_available:
        blocking.append("target_unavailable")
    if item.status not in {"completed", "partially_completed"}:
        blocking.append("import_not_completed")
    raw_valid_rows = item.quality_report.get("valid_rows", 0)
    valid_rows = raw_valid_rows if isinstance(raw_valid_rows, int) else 0
    raw_invalid_rows = item.quality_report.get("invalid_rows", 0)
    invalid_rows = raw_invalid_rows if isinstance(raw_invalid_rows, int) else 0
    missingness = invalid_rows / item.total_rows if item.total_rows else 1.0
    profile_text = {
        TrainingProfile.FAST_DEMO: (
            "Existing defaults with the smallest supported bounded run."
        ),
        TrainingProfile.BALANCED: "Existing defaults with standard bounded evaluation.",
        TrainingProfile.THOROUGH: (
            "Existing AutoML workflow; execution limits remain server controlled."
        ),
    }[payload.profile]
    return ReadinessResponse(
        ready=not blocking and valid_rows >= 2,
        dataset_size=item.total_rows,
        valid_rows=valid_rows,
        selected_features=payload.features,
        target_available=target_available,
        missingness_rate=round(missingness, 4),
        time_coverage=None,
        blocking_issues=blocking,
        profile_summary=profile_text,
        deployment_consequence=(
            "Training registers a version; it does not promote or deploy it "
            "automatically."
        ),
    )
