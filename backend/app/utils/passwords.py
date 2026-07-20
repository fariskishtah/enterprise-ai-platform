"""Password hashing and password policy utilities."""

from pwdlib import PasswordHash


class PasswordPolicyError(ValueError):
    """Raised when a password does not meet the platform policy."""


class PasswordHasher:
    """Password hashing adapter backed by pwdlib."""

    def __init__(self, password_hash: PasswordHash | None = None) -> None:
        self._password_hash = password_hash or PasswordHash.recommended()

    def hash(self, password: str) -> str:
        """Hash a plaintext password."""
        return self._password_hash.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        """Verify a plaintext password against a stored hash."""
        return self._password_hash.verify(password, password_hash)


def validate_password_strength(password: str) -> None:
    """Require a practical passphrase length without composition rules."""
    if len(password) < 12:
        msg = "Password must be at least 12 characters long."
        raise PasswordPolicyError(msg)
    if len(password) > 128:
        msg = "Password must be at most 128 characters long."
        raise PasswordPolicyError(msg)
