"""Password hashing and password policy utilities."""

import re

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
    """Validate the minimum password strength policy."""
    if len(password) < 12:
        msg = "Password must be at least 12 characters long."
        raise PasswordPolicyError(msg)
    if len(password) > 128:
        msg = "Password must be at most 128 characters long."
        raise PasswordPolicyError(msg)
    if any(character.isspace() for character in password):
        msg = "Password must not contain whitespace."
        raise PasswordPolicyError(msg)
    if re.search(r"[a-z]", password) is None:
        msg = "Password must include a lowercase letter."
        raise PasswordPolicyError(msg)
    if re.search(r"[A-Z]", password) is None:
        msg = "Password must include an uppercase letter."
        raise PasswordPolicyError(msg)
    if re.search(r"\d", password) is None:
        msg = "Password must include a number."
        raise PasswordPolicyError(msg)
    if re.search(r"[^A-Za-z0-9]", password) is None:
        msg = "Password must include a special character."
        raise PasswordPolicyError(msg)
