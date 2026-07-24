"""Public unified audit contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    occurred_at: datetime
    company_id: UUID
    actor_user_id: UUID | None
    actor_role: str | None
    action: str
    resource_type: str
    resource_id: str | None
    result: str
    request_id: str | None
    correlation_id: str | None
    source_ip: str | None
    user_agent: str | None
    safe_metadata: dict[str, object]
    before_summary: str | None
    after_summary: str | None
    retention_class: str


class AuditEventPage(BaseModel):
    items: list[AuditEventResponse]
    total: int
    limit: int
    offset: int
