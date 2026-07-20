"""Authentication application service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from app.config.settings import Settings
from app.models.user import User
from app.repositories.users import UserRepository
from app.services.exceptions import (
    InactiveUserError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)
from app.services.users import UserService
from app.utils.jwt import (
    TokenClaims,
    TokenDecodeError,
    TokenType,
    create_jwt_token,
    decode_jwt_token,
)
from app.utils.passwords import PasswordHasher
from app.utils.security import as_utc, hash_token, normalize_email, utc_now


@dataclass(frozen=True)
class IssuedTokenPair:
    """Access and refresh token pair returned after authentication."""

    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class AuthenticationService:
    """Application use cases for authentication."""

    def __init__(
        self,
        *,
        settings: Settings,
        repository: UserRepository,
        user_service: UserService,
        password_hasher: PasswordHasher,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._user_service = user_service
        self._password_hasher = password_hasher

    async def register(self, *, email: str, password: str) -> User:
        """Register a new operator user."""
        return await self._user_service.create_user(email=email, password=password)

    async def login(self, *, email: str, password: str) -> IssuedTokenPair:
        """Authenticate a user and issue a token pair."""
        user = await self._repository.get_by_email(normalize_email(email))
        if user is None:
            raise InvalidCredentialsError("Invalid email or password.")
        if not self._password_hasher.verify(password, user.hashed_password):
            raise InvalidCredentialsError("Invalid email or password.")
        if not user.is_active:
            raise InactiveUserError("User is inactive.")

        return await self._issue_token_pair(user)

    async def refresh(self, *, refresh_token: str) -> IssuedTokenPair:
        """Rotate a refresh token and issue a new token pair."""
        claims = self._decode_refresh_token(refresh_token)
        persisted_token = await self._repository.get_refresh_token(
            jti=claims.jti,
            token_hash=hash_token(refresh_token),
        )
        now = utc_now()
        if (
            persisted_token is None
            or persisted_token.revoked_at is not None
            or as_utc(persisted_token.expires_at) <= now
        ):
            raise InvalidRefreshTokenError("Refresh token is invalid.")

        user = await self._repository.get_by_id(claims.sub)
        if user is None:
            raise InvalidRefreshTokenError("Refresh token is invalid.")
        if not user.is_active:
            raise InactiveUserError("User is inactive.")

        await self._repository.revoke_refresh_token(
            refresh_token=persisted_token,
            revoked_at=now,
        )
        return await self._issue_token_pair(user)

    async def logout(self, *, refresh_token: str) -> None:
        """Revoke a refresh token."""
        claims = self._decode_refresh_token(refresh_token)
        persisted_token = await self._repository.get_refresh_token(
            jti=claims.jti,
            token_hash=hash_token(refresh_token),
        )
        if persisted_token is None:
            raise InvalidRefreshTokenError("Refresh token is invalid.")

        if persisted_token.revoked_at is None:
            await self._repository.revoke_refresh_token(
                refresh_token=persisted_token,
                revoked_at=utc_now(),
            )
        await self._repository.commit()

    async def revoke_all_user_refresh_tokens(self, *, user_id: UUID) -> None:
        """Revoke all active refresh tokens for a user."""
        await self._repository.revoke_user_refresh_tokens(
            user_id=user_id,
            revoked_at=utc_now(),
        )
        await self._repository.commit()

    async def _issue_token_pair(self, user: User) -> IssuedTokenPair:
        access_token = create_jwt_token(
            subject=user.id,
            token_type=TokenType.ACCESS,
            secret_key=self._settings.secret_key.get_secret_value(),
            algorithm=self._settings.jwt_algorithm,
            issuer=self._settings.jwt_issuer,
            audience=self._settings.jwt_audience,
            expires_delta=timedelta(
                minutes=self._settings.access_token_expire_minutes,
            ),
            additional_claims={"email": user.email, "role": user.role.value},
        )
        refresh_expiration = timedelta(days=self._settings.refresh_token_expire_days)
        refresh_token = create_jwt_token(
            subject=user.id,
            token_type=TokenType.REFRESH,
            secret_key=self._settings.secret_key.get_secret_value(),
            algorithm=self._settings.jwt_algorithm,
            issuer=self._settings.jwt_issuer,
            audience=self._settings.jwt_audience,
            expires_delta=refresh_expiration,
        )
        await self._repository.create_refresh_token(
            user_id=user.id,
            jti=refresh_token.jti,
            token_hash=hash_token(refresh_token.token),
            expires_at=utc_now() + refresh_expiration,
        )
        await self._repository.commit()

        return IssuedTokenPair(
            access_token=access_token.token,
            refresh_token=refresh_token.token,
            token_type="bearer",
            expires_in=access_token.expires_in,
        )

    def _decode_refresh_token(self, refresh_token: str) -> TokenClaims:
        try:
            return decode_jwt_token(
                token=refresh_token,
                secret_key=self._settings.secret_key.get_secret_value(),
                algorithm=self._settings.jwt_algorithm,
                issuer=self._settings.jwt_issuer,
                audience=self._settings.jwt_audience,
                expected_type=TokenType.REFRESH,
            )
        except TokenDecodeError as exc:
            raise InvalidRefreshTokenError("Refresh token is invalid.") from exc
