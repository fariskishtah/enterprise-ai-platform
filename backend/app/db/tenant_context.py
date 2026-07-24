"""Dependency-light request tenant context."""

from contextvars import ContextVar, Token
from uuid import UUID

_COMPANY_ID: ContextVar[UUID | None] = ContextVar("tenant_company_id", default=None)


def bind_tenant(company_id: UUID) -> Token[UUID | None]:
    return _COMPANY_ID.set(company_id)


def reset_tenant(token: Token[UUID | None]) -> None:
    _COMPANY_ID.reset(token)


def current_tenant() -> UUID | None:
    return _COMPANY_ID.get()


def clear_tenant() -> None:
    _COMPANY_ID.set(None)
