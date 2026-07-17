"""User routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.user import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Return the authenticated user",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid access token.",
        },
        status.HTTP_403_FORBIDDEN: {"description": "User account is inactive."},
    },
)
async def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """Return the authenticated user."""
    return UserResponse.model_validate(current_user)
