"""Company-scoped user and account lifecycle application service."""

import secrets
from datetime import timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.models.user import RefreshToken, User, UserRole
from app.repositories.users import UserRepository
from app.services.exceptions import (
    AccountLifecycleError,
    DuplicateEmailError,
    InvalidPasswordResetTokenError,
)
from app.utils.passwords import PasswordHasher, validate_password_strength
from app.utils.security import as_utc, hash_token, normalize_email, utc_now


class UserService:
    """Application use cases for users."""

    def __init__(
        self,
        *,
        repository: UserRepository,
        password_hasher: PasswordHasher,
    ) -> None:
        self._repository = repository
        self._password_hasher = password_hasher

    async def create_user(
        self,
        *,
        email: str,
        password: str,
        role: UserRole = UserRole.OPERATOR,
        company_id: UUID | None = None,
        company_name: str | None = None,
    ) -> User:
        """Create a user with a unique email address."""
        normalized_email = normalize_email(email)
        validate_password_strength(password)
        existing_user = await self._repository.get_by_email(normalized_email)
        if existing_user is not None:
            raise DuplicateEmailError("Email is already registered.")

        try:
            user = await self._repository.create_user(
                email=normalized_email,
                hashed_password=self._password_hasher.hash(password),
                role=role,
                company_id=company_id,
                company_name=company_name,
            )
            await self._repository.commit()
        except IntegrityError as exc:
            await self._repository.rollback()
            raise DuplicateEmailError("Email is already registered.") from exc

        return user

    async def list_company_users(
        self,
        *,
        actor: User,
        role: UserRole | None,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[User], int]:
        return await self._repository.list_company_users(
            company_id=actor.company_id,
            role=role,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

    async def create_company_user(
        self,
        *,
        actor: User,
        email: str,
        password: str,
        role: UserRole,
    ) -> User:
        if actor.role is not UserRole.ADMIN:
            raise AccountLifecycleError("Administrator role is required.")
        return await self.create_user(
            email=email,
            password=password,
            role=role,
            company_id=actor.company_id,
        )

    async def update_company_user(
        self,
        *,
        actor: User,
        user_id: UUID,
        role: UserRole | None,
        is_active: bool | None,
    ) -> User:
        target = await self._repository.get_by_id_in_company(user_id, actor.company_id)
        if target is None:
            raise AccountLifecycleError("User not found.")
        removes_active_admin = (
            target.role is UserRole.ADMIN
            and target.is_active
            and (
                (role is not None and role is not UserRole.ADMIN) or is_active is False
            )
        )
        if removes_active_admin and (
            await self._repository.count_active_admins(actor.company_id) <= 1
        ):
            raise AccountLifecycleError(
                "The last active administrator cannot be removed."
            )
        if role is not None:
            target.role = role
        if is_active is not None:
            target.is_active = is_active
            if not is_active:
                await self._repository.revoke_user_refresh_tokens(
                    user_id=target.id, revoked_at=utc_now()
                )
        await self._repository.commit()
        await self._repository.refresh_user(target)
        return target

    async def change_password(
        self, *, user: User, current_password: str, new_password: str
    ) -> None:
        if not self._password_hasher.verify(current_password, user.hashed_password):
            raise AccountLifecycleError("Current password is incorrect.")
        validate_password_strength(new_password)
        if self._password_hasher.verify(new_password, user.hashed_password):
            raise AccountLifecycleError(
                "The new password must differ from the current password."
            )
        await self._repository.update_password(
            user, self._password_hasher.hash(new_password)
        )
        await self._repository.revoke_user_refresh_tokens(
            user_id=user.id, revoked_at=utc_now()
        )
        await self._repository.commit()

    async def initiate_password_reset(
        self, *, email: str, expiry_minutes: int
    ) -> tuple[User | None, str | None]:
        user = await self._repository.get_by_email(normalize_email(email))
        if user is None or not user.is_active:
            return None, None
        token = secrets.token_urlsafe(48)
        await self._repository.create_password_reset_token(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=utc_now() + timedelta(minutes=expiry_minutes),
        )
        await self._repository.commit()
        return user, token

    async def complete_password_reset(self, *, token: str, new_password: str) -> User:
        entity = await self._repository.get_password_reset_token(hash_token(token))
        now = utc_now()
        if (
            entity is None
            or entity.used_at is not None
            or as_utc(entity.expires_at) <= now
        ):
            raise InvalidPasswordResetTokenError(
                "Password reset token is invalid or expired."
            )
        user = await self._repository.get_by_id(entity.user_id)
        if user is None or not user.is_active:
            raise InvalidPasswordResetTokenError(
                "Password reset token is invalid or expired."
            )
        validate_password_strength(new_password)
        await self._repository.update_password(
            user, self._password_hasher.hash(new_password)
        )
        entity.used_at = now
        await self._repository.revoke_user_refresh_tokens(
            user_id=user.id, revoked_at=now
        )
        await self._repository.commit()
        return user

    async def list_sessions(self, user_id: UUID) -> list[RefreshToken]:
        return await self._repository.list_active_sessions(user_id)

    async def revoke_session(self, *, user_id: UUID, session_id: UUID) -> bool:
        session = await self._repository.get_active_session(
            session_id=session_id, user_id=user_id
        )
        if session is None:
            return False
        await self._repository.revoke_refresh_token(
            refresh_token=session, revoked_at=utc_now()
        )
        await self._repository.commit()
        return True

    async def revoke_other_sessions(
        self, *, user_id: UUID, current_refresh_token: str
    ) -> None:
        persisted = await self._repository.get_refresh_token_by_hash(
            hash_token(current_refresh_token)
        )
        if persisted is None or persisted.user_id != user_id:
            raise AccountLifecycleError("Current session could not be verified.")
        await self._repository.revoke_other_user_refresh_tokens(
            user_id=user_id,
            current_session_id=persisted.id,
            revoked_at=utc_now(),
        )
        await self._repository.commit()

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Return a user by ID."""
        return await self._repository.get_by_id(user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Return a user by normalized email address."""
        return await self._repository.get_by_email(normalize_email(email))
