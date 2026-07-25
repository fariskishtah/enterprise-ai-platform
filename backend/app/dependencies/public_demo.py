"""Request-scoped public-demo tenant classification."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_user
from app.dependencies.database import get_db_session
from app.ml.base import TrainerKey
from app.ml.registry import build_registered_model_name
from app.models.manufacturing import Company
from app.models.user import User


async def is_public_demo_account(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> bool:
    """Return the persisted tenant marker; never infer it from a role or email."""
    value = await session.scalar(
        select(Company.is_public_demo).where(Company.id == current_user.company_id)
    )
    return value is True


def public_demo_model_prefix(user: User) -> str:
    """Return an unambiguous MLflow namespace for one isolated company."""
    return f"public_demo_{user.company_id.hex}"


def registered_model_name_for_request(
    *,
    current_user: User,
    public_demo: bool,
    requested_name: str | None,
    key: TrainerKey,
    default_prefix: str,
) -> str:
    """Resolve a model name without allowing demo tenants to share a namespace."""
    if not public_demo:
        return requested_name or build_registered_model_name(key, prefix=default_prefix)
    if requested_name is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Public demo model names are assigned automatically.",
        )
    return build_registered_model_name(
        key,
        prefix=public_demo_model_prefix(current_user),
    )


def ensure_public_demo_model_scope(
    *,
    current_user: User,
    public_demo: bool,
    registered_model_name: str,
) -> None:
    """Hide model references outside a public user's company namespace."""
    expected = f"{public_demo_model_prefix(current_user)}_"
    if public_demo and not registered_model_name.startswith(expected):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested registered model was not found.",
        )


async def require_public_demo_model_scope(
    registered_model_name: str,
    current_user: Annotated[User, Depends(get_current_user)],
    public_demo: Annotated[bool, Depends(is_public_demo_account)],
) -> None:
    """FastAPI dependency for model-name path parameters."""
    ensure_public_demo_model_scope(
        current_user=current_user,
        public_demo=public_demo,
        registered_model_name=registered_model_name,
    )


async def require_non_public_demo_account(
    public_demo: Annotated[bool, Depends(is_public_demo_account)],
) -> None:
    """Keep public users off unbounded legacy compute paths."""
    if public_demo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Public demo accounts must use the bounded background training "
                "workflow."
            ),
        )
