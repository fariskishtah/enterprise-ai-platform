"""Authentication unit tests."""

import logging
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
JWT_SECRET = "test-secret-key-with-sufficient-entropy"
JWT_ISSUER = "test-platform"
JWT_AUDIENCE = "test-api"


def _create_token(
    token_type: TokenType,
    *,
    expires_delta: timedelta = timedelta(minutes=15),
) -> str:
    return create_jwt_token(
        subject=uuid4(),
        token_type=token_type,
        secret_key=JWT_SECRET,
        algorithm="HS256",
        issuer=JWT_ISSUER,
        audience=JWT_AUDIENCE,
        expires_delta=expires_delta,
    ).token


def _decode_token(token: str, expected_type: TokenType) -> None:
    decode_jwt_token(
        token=token,
        secret_key=JWT_SECRET,
        algorithm="HS256",
        issuer=JWT_ISSUER,
        audience=JWT_AUDIENCE,
        expected_type=expected_type,
    )


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


def test_password_policy_accepts_long_passphrase() -> None:
    """The policy permits memorable passphrases without composition rules."""
    from app.utils.passwords import validate_password_strength

    validate_password_strength("correct horse battery staple")


@pytest.mark.parametrize(
    ("created_type", "expected_type"),
    [
        (TokenType.ACCESS, TokenType.REFRESH),
        (TokenType.REFRESH, TokenType.ACCESS),
    ],
)
def test_jwt_rejects_cross_use(
    created_type: TokenType,
    expected_type: TokenType,
) -> None:
    """Access and refresh JWTs cannot be used interchangeably."""
    token = _create_token(created_type)

    with pytest.raises(TokenDecodeError):
        _decode_token(token, expected_type)


@pytest.mark.parametrize(
    "token",
    ["not-a-jwt", "one.two.three", ""],
)
def test_jwt_rejects_malformed_tokens(token: str) -> None:
    """Malformed JWTs fail with the safe decoder exception."""
    with pytest.raises(TokenDecodeError):
        _decode_token(token, TokenType.ACCESS)


def test_jwt_rejects_expired_token() -> None:
    """Expired JWTs are rejected."""
    token = _create_token(
        TokenType.ACCESS,
        expires_delta=timedelta(seconds=-1),
    )

    with pytest.raises(TokenDecodeError):
        _decode_token(token, TokenType.ACCESS)


@pytest.mark.parametrize(
    ("issuer", "audience"),
    [("wrong-issuer", JWT_AUDIENCE), (JWT_ISSUER, "wrong-audience")],
)
def test_jwt_rejects_wrong_issuer_or_audience(
    issuer: str,
    audience: str,
) -> None:
    """JWTs are bound to the configured issuer and API audience."""
    token = _create_token(TokenType.ACCESS)

    with pytest.raises(TokenDecodeError):
        decode_jwt_token(
            token=token,
            secret_key=JWT_SECRET,
            algorithm="HS256",
            issuer=issuer,
            audience=audience,
            expected_type=TokenType.ACCESS,
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


def test_require_roles_rejects_disallowed_role(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """RBAC dependency rejects users without an allowed role."""
    caplog.set_level(logging.WARNING, logger="app.security.audit")
    dependency = require_roles(UserRole.ADMIN)
    user_id = uuid4()
    user = User(
        id=user_id,
        email="operator@example.com",
        hashed_password="hash",
        role=UserRole.OPERATOR,
    )

    with pytest.raises(HTTPException) as exc_info:
        dependency(user)

    assert exc_info.value.status_code == 403
    audit_record = next(
        record
        for record in caplog.records
        if record.name == "app.security.audit"
        and record.audit_event == "privileged_authorization"
    )
    assert audit_record.outcome == "denied"
    assert audit_record.reason == "insufficient_role"
    assert audit_record.actor_role == "operator"
    assert audit_record.required_roles == "admin"
    assert str(user_id) not in str(audit_record.__dict__)


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
