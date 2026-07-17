"""Authentication unit tests."""

from datetime import timedelta
from uuid import uuid4

import pytest
from app.dependencies.auth import require_roles
from app.models.user import User, UserRole
from app.repositories.users import UserRepository
from app.services.exceptions import DuplicateEmailError
from app.services.users import UserService
from app.utils.jwt import (
    TokenDecodeError,
    TokenType,
    create_jwt_token,
    decode_jwt_token,
)
from app.utils.passwords import PasswordHasher, PasswordPolicyError
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

VALID_PASSWORD = "ValidPassword1!"


def test_password_hasher_hashes_and_verifies_password() -> None:
    """Password hashes are non-plaintext and verifiable."""
    hasher = PasswordHasher()

    password_hash = hasher.hash(VALID_PASSWORD)

    assert password_hash != VALID_PASSWORD
    assert hasher.verify(VALID_PASSWORD, password_hash)
    assert not hasher.verify("WrongPassword1!", password_hash)


def test_password_policy_rejects_weak_password() -> None:
    """The password policy rejects weak passwords."""
    from app.utils.passwords import validate_password_strength

    with pytest.raises(PasswordPolicyError):
        validate_password_strength("weak")


def test_jwt_rejects_wrong_token_type() -> None:
    """JWT decoding enforces token purpose."""
    secret_key = "test-secret-key-with-sufficient-entropy"
    created_token = create_jwt_token(
        subject=uuid4(),
        token_type=TokenType.ACCESS,
        secret_key=secret_key,
        algorithm="HS256",
        expires_delta=timedelta(minutes=15),
    )

    with pytest.raises(TokenDecodeError):
        decode_jwt_token(
            token=created_token.token,
            secret_key=secret_key,
            algorithm="HS256",
            expected_type=TokenType.REFRESH,
        )


def test_require_roles_accepts_allowed_role() -> None:
    """RBAC dependency accepts users with an allowed role."""
    dependency = require_roles(UserRole.ADMIN)
    user = User(
        email="admin@example.com",
        hashed_password="hash",
        role=UserRole.ADMIN,
    )

    assert dependency(user) is user


def test_require_roles_rejects_disallowed_role() -> None:
    """RBAC dependency rejects users without an allowed role."""
    dependency = require_roles(UserRole.ADMIN)
    user = User(
        email="operator@example.com",
        hashed_password="hash",
        role=UserRole.OPERATOR,
    )

    with pytest.raises(HTTPException) as exc_info:
        dependency(user)

    assert exc_info.value.status_code == 403


@pytest.mark.anyio
async def test_user_service_rejects_duplicate_email(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """User service enforces unique normalized email addresses."""
    async with session_factory() as session:
        repository = UserRepository(session)
        service = UserService(
            repository=repository,
            password_hasher=PasswordHasher(),
        )

        await service.create_user(email="USER@example.com", password=VALID_PASSWORD)

        with pytest.raises(DuplicateEmailError):
            await service.create_user(email="user@example.com", password=VALID_PASSWORD)
