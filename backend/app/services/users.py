"""User application service."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.models.user import User, UserRole
from app.repositories.users import UserRepository
from app.services.exceptions import DuplicateEmailError
from app.utils.passwords import PasswordHasher, validate_password_strength
from app.utils.security import normalize_email


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
            )
            await self._repository.commit()
        except IntegrityError as exc:
            await self._repository.rollback()
            raise DuplicateEmailError("Email is already registered.") from exc

        return user

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Return a user by ID."""
        return await self._repository.get_by_id(user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Return a user by normalized email address."""
        return await self._repository.get_by_email(normalize_email(email))
