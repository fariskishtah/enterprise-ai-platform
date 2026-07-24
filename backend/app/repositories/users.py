"""Persistence adapter for users and refresh tokens."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.manufacturing import Company
from app.models.user import PasswordResetToken, RefreshToken, User, UserRole
from app.repositories.manufacturing import normalize_name


class UserRepository:
    """Repository for user and refresh-token persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Return a user by primary key."""
        return await self._session.get(User, user_id)

    async def get_by_id_in_company(
        self, user_id: UUID, company_id: UUID
    ) -> User | None:
        statement = select(User).where(
            User.id == user_id, User.company_id == company_id
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

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
        company_id: UUID | None = None,
        company_name: str | None = None,
    ) -> User:
        """Create a user."""
        resolved_company_id = company_id
        if resolved_company_id is None:
            name = company_name or f"Workspace for {email}"
            company = Company(
                name=name,
                normalized_name=normalize_name(name),
                description="Account workspace created during local registration.",
            )
            self._session.add(company)
            await self._session.flush()
            resolved_company_id = company.id
        user = User(
            email=email,
            hashed_password=hashed_password,
            role=role,
            company_id=resolved_company_id,
        )
        self._session.add(user)
        await self._session.flush()
        await self._session.refresh(user)
        return user

    async def list_company_users(
        self,
        *,
        company_id: UUID,
        role: UserRole | None,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[User], int]:
        statement = select(User).where(User.company_id == company_id)
        if role is not None:
            statement = statement.where(User.role == role)
        if is_active is not None:
            statement = statement.where(User.is_active.is_(is_active))
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            or 0
        )
        users = list(
            (
                await self._session.execute(
                    statement.order_by(User.created_at.asc(), User.id.asc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return users, total

    async def count_active_admins(self, company_id: UUID) -> int:
        """Lock active administrator rows before an access-removing mutation."""
        rows = await self._session.scalars(
            select(User.id)
            .where(
                User.company_id == company_id,
                User.role == UserRole.ADMIN,
                User.is_active.is_(True),
            )
            .with_for_update()
        )
        return len(rows.all())

    async def update_password(self, user: User, hashed_password: str) -> None:
        user.hashed_password = hashed_password
        await self._session.flush()

    async def refresh_user(self, user: User) -> None:
        await self._session.refresh(user)

    async def create_password_reset_token(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> PasswordResetToken:
        entity = PasswordResetToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def get_password_reset_token(
        self, token_hash: str
    ) -> PasswordResetToken | None:
        statement = select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def list_active_sessions(self, user_id: UUID) -> list[RefreshToken]:
        statement = (
            select(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > datetime.now().astimezone(),
            )
            .order_by(RefreshToken.created_at.desc())
        )
        return list((await self._session.execute(statement)).scalars().all())

    async def get_active_session(
        self, *, session_id: UUID, user_id: UUID
    ) -> RefreshToken | None:
        statement = select(RefreshToken).where(
            RefreshToken.id == session_id,
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def create_refresh_token(
        self,
        *,
        user_id: UUID,
        jti: UUID,
        token_hash: str,
        expires_at: datetime,
        user_agent_summary: str | None = None,
        source_ip: str | None = None,
    ) -> RefreshToken:
        """Persist refresh-token metadata."""
        refresh_token = RefreshToken(
            user_id=user_id,
            jti=jti,
            token_hash=token_hash,
            expires_at=expires_at,
            user_agent_summary=user_agent_summary,
            source_ip=source_ip,
            last_seen_at=datetime.now().astimezone(),
        )
        self._session.add(refresh_token)
        await self._session.flush()
        await self._session.refresh(refresh_token)
        return refresh_token

    async def revoke_other_user_refresh_tokens(
        self, *, user_id: UUID, current_session_id: UUID, revoked_at: datetime
    ) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.id != current_session_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )

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

    async def get_refresh_token_by_hash(self, token_hash: str) -> RefreshToken | None:
        statement = select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

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
