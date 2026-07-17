"""Persistence adapter for users and refresh tokens."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import RefreshToken, User, UserRole


class UserRepository:
    """Repository for user and refresh-token persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Return a user by primary key."""
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Return a user by normalized email address."""
        statement = select(User).where(User.email == email)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def create_user(
        self,
        *,
        email: str,
        hashed_password: str,
        role: UserRole,
    ) -> User:
        """Create a user."""
        user = User(email=email, hashed_password=hashed_password, role=role)
        self._session.add(user)
        await self._session.flush()
        await self._session.refresh(user)
        return user

    async def create_refresh_token(
        self,
        *,
        user_id: UUID,
        jti: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshToken:
        """Persist refresh-token metadata."""
        refresh_token = RefreshToken(
            user_id=user_id,
            jti=jti,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self._session.add(refresh_token)
        await self._session.flush()
        await self._session.refresh(refresh_token)
        return refresh_token

    async def get_refresh_token(
        self,
        *,
        jti: UUID,
        token_hash: str,
    ) -> RefreshToken | None:
        """Return a refresh token by its JWT ID and digest."""
        statement = select(RefreshToken).where(
            RefreshToken.jti == jti,
            RefreshToken.token_hash == token_hash,
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def revoke_refresh_token(
        self,
        *,
        refresh_token: RefreshToken,
        revoked_at: datetime,
    ) -> None:
        """Mark a refresh token as revoked."""
        refresh_token.revoked_at = revoked_at
        await self._session.flush()

    async def revoke_user_refresh_tokens(
        self,
        *,
        user_id: UUID,
        revoked_at: datetime,
    ) -> None:
        """Mark all active refresh tokens for a user as revoked."""
        statement = (
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )
        await self._session.execute(statement)

    async def commit(self) -> None:
        """Commit the active transaction."""
        await self._session.commit()

    async def rollback(self) -> None:
        """Roll back the active transaction."""
        await self._session.rollback()
