"""Safe, append-only audit event application service."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.models.user import AuditEvent, User
from app.observability.logging import current_correlation_id, current_request_id
from app.repositories.audit import AuditRepository

_FORBIDDEN_KEYS = frozenset(
    {
        "password",
        "hashed_password",
        "token",
        "access_token",
        "refresh_token",
        "reset_token",
        "secret",
        "document_text",
        "features",
        "prediction_payload",
    }
)
_FORBIDDEN_KEY_PARTS = (
    "authorization",
    "cookie",
    "credential",
    "document_text",
    "password",
    "prediction_payload",
    "secret",
    "token",
)


def safe_audit_metadata(values: dict[str, object] | None) -> dict[str, object]:
    """Return bounded scalar metadata and reject known sensitive keys."""
    if values is None:
        return {}
    sanitized: dict[str, object] = {}
    for raw_key, raw_value in list(values.items())[:20]:
        key = str(raw_key).strip().lower()[:64]
        if (
            not key
            or key in _FORBIDDEN_KEYS
            or any(part in key for part in _FORBIDDEN_KEY_PARTS)
        ):
            continue
        if isinstance(raw_value, (bool, int, float)) or raw_value is None:
            sanitized[key] = raw_value
        elif isinstance(raw_value, str):
            sanitized[key] = raw_value[:256]
    return sanitized


class AuditService:
    """Record and query immutable events within an explicit tenant."""

    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    async def record(
        self,
        *,
        company_id: UUID,
        action: str,
        resource_type: str,
        result: str,
        actor: User | None = None,
        resource_id: str | UUID | None = None,
        source_ip: str | None = None,
        user_agent: str | None = None,
        metadata: dict[str, object] | None = None,
        before_summary: str | None = None,
        after_summary: str | None = None,
        retention_class: str = "security",
        commit: bool = True,
    ) -> AuditEvent:
        event = await self._repository.append(
            company_id=company_id,
            actor_user_id=actor.id if actor else None,
            actor_role=actor.role.value if actor else None,
            action=action[:128],
            resource_type=resource_type[:64],
            resource_id=str(resource_id)[:128] if resource_id is not None else None,
            result=result,
            request_id=current_request_id(),
            correlation_id=current_correlation_id(),
            source_ip=source_ip[:64] if source_ip else None,
            user_agent=user_agent[:255] if user_agent else None,
            safe_metadata=safe_audit_metadata(metadata),
            before_summary=before_summary[:1000] if before_summary else None,
            after_summary=after_summary[:1000] if after_summary else None,
            retention_class=retention_class[:32],
        )
        if commit:
            await self._repository.commit()
        return event

    async def list_events(
        self,
        *,
        company_id: UUID,
        actor_user_id: UUID | None,
        action: str | None,
        result: str | None,
        resource_type: str | None,
        resource_id: str | None,
        start_at: datetime | None,
        end_at: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AuditEvent], int]:
        return await self._repository.list_events(
            company_id=company_id,
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
