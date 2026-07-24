"""Company-scoped unified audit event API."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.dependencies.auth import require_roles
from app.dependencies.services import get_audit_service
from app.models.user import User, UserRole
from app.schemas.audit import AuditEventPage, AuditEventResponse
from app.services.audit import AuditService

router = APIRouter(prefix="/audit-events", tags=["audit"])


@router.get("", response_model=AuditEventPage)
async def list_audit_events(
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[AuditService, Depends(get_audit_service)],
    actor_user_id: UUID | None = None,
    action: Annotated[str | None, Query(max_length=128)] = None,
    result: Literal["success", "failure"] | None = None,
    resource_type: Annotated[str | None, Query(max_length=64)] = None,
    resource_id: Annotated[str | None, Query(max_length=128)] = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> AuditEventPage:
    items, total = await service.list_events(
        company_id=current_user.company_id,
        actor_user_id=actor_user_id,
        action=action,
        result=result,
        resource_type=resource_type,
        resource_id=resource_id,
        start_at=start_at,
        end_at=end_at,
        limit=limit,
        offset=offset,
    )
    return AuditEventPage(
        items=[AuditEventResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/export")
async def export_audit_events(
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[AuditService, Depends(get_audit_service)],
    export_format: Literal["csv", "json"] = "csv",
) -> Response:
    items, _ = await service.list_events(
        company_id=current_user.company_id,
        actor_user_id=None,
        action=None,
        result=None,
        resource_type=None,
        resource_id=None,
        start_at=None,
        end_at=None,
        limit=100,
        offset=0,
    )
    public = [
        AuditEventResponse.model_validate(item).model_dump(mode="json")
        for item in items
    ]
    if export_format == "json":
        return Response(
            json.dumps(public, separators=(",", ":")),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="audit-events.json"'},
        )
    output = io.StringIO()
    fields = [
        "id",
        "occurred_at",
        "actor_user_id",
        "actor_role",
        "action",
        "resource_type",
        "resource_id",
        "result",
        "request_id",
        "correlation_id",
        "retention_class",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(public)
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit-events.csv"'},
    )
