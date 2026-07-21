"""Narrow Redis-backed rate limiting for public authentication endpoints."""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import Awaitable
from functools import lru_cache
from typing import Annotated, Any, Protocol, cast

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config.settings import Settings, get_settings
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.observability.logging import emit_safe

logger = logging.getLogger("app.security.audit")

_INCREMENT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


class AuthRateLimitStoreError(RuntimeError):
    """Raised when the rate-limit store returns an unusable response."""


class AuthRateLimitStore(Protocol):
    """Storage boundary used by the authentication rate limiter."""

    async def increment(self, key: str, window_seconds: int) -> tuple[int, int]:
        """Increment a key and return its count and remaining TTL."""


class RedisAuthRateLimitStore:
    """Atomic fixed-window rate-limit storage backed by Redis."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def increment(self, key: str, window_seconds: int) -> tuple[int, int]:
        """Increment and initialize expiry atomically in Redis."""
        result = await cast(
            Awaitable[Any],
            self._client.eval(
                _INCREMENT_SCRIPT,
                1,
                key,
                str(window_seconds),
            ),
        )
        if not isinstance(result, (list, tuple)) or len(result) != 2:
            raise AuthRateLimitStoreError("Invalid rate-limit store response.")
        try:
            return int(result[0]), int(result[1])
        except (TypeError, ValueError) as exc:
            raise AuthRateLimitStoreError("Invalid rate-limit store response.") from exc


@lru_cache
def _redis_store(redis_url: str) -> RedisAuthRateLimitStore:
    return RedisAuthRateLimitStore(Redis.from_url(redis_url))


def get_auth_rate_limit_store(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthRateLimitStore:
    """Return the process-cached Redis rate-limit store."""
    return _redis_store(settings.redis_url)


def _privacy_safe_key(request: Request, secret_key: str) -> str:
    client_host = request.client.host if request.client is not None else "unknown"
    source = f"{request.url.path}|{client_host}".encode()
    digest = hmac.new(secret_key.encode(), source, hashlib.sha256).hexdigest()
    return f"auth-rate-limit:v1:{digest}"


async def enforce_auth_rate_limit(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[AuthRateLimitStore, Depends(get_auth_rate_limit_store)],
) -> None:
    """Enforce a bounded per-client limit for the current auth endpoint."""
    if not settings.auth_rate_limit_enabled:
        return

    try:
        count, ttl = await store.increment(
            _privacy_safe_key(
                request,
                settings.secret_key.get_secret_value(),
            ),
            settings.auth_rate_limit_window_seconds,
        )
    except (RedisError, AuthRateLimitStoreError):
        emit_safe(
            logger,
            logging.ERROR,
            "auth_rate_limit_unavailable",
            extra={"error_kind": "rate_limit_store_unavailable"},
        )
        return

    if count <= settings.auth_rate_limit_requests:
        return

    retry_after = max(
        1,
        min(ttl, settings.auth_rate_limit_window_seconds, 3600),
    )
    emit_safe(
        logger,
        logging.WARNING,
        "security_audit",
        extra={
            "audit_event": "authentication_rate_limit",
            "outcome": "denied",
            "reason": "rate_limited",
        },
    )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many authentication attempts.",
        headers={"Retry-After": str(retry_after)},
    )


def _privacy_safe_mutation_key(
    request: Request,
    user_id: object,
    secret_key: str,
) -> str:
    source = f"{request.url.path}|{user_id}".encode()
    digest = hmac.new(secret_key.encode(), source, hashlib.sha256).hexdigest()
    return f"mutation-rate-limit:v1:{digest}"


async def enforce_mutation_rate_limit(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[AuthRateLimitStore, Depends(get_auth_rate_limit_store)],
) -> None:
    """Fail closed when a sensitive authenticated mutation cannot be limited."""
    if not settings.mutation_rate_limit_enabled:
        return

    try:
        count, ttl = await store.increment(
            _privacy_safe_mutation_key(
                request,
                current_user.id,
                settings.secret_key.get_secret_value(),
            ),
            settings.mutation_rate_limit_window_seconds,
        )
    except (RedisError, AuthRateLimitStoreError) as exc:
        emit_safe(
            logger,
            logging.ERROR,
            "mutation_rate_limit_unavailable",
            extra={"error_kind": "rate_limit_store_unavailable"},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A required service is unavailable.",
        ) from exc

    if count <= settings.mutation_rate_limit_requests:
        return

    retry_after = max(
        1,
        min(ttl, settings.mutation_rate_limit_window_seconds, 3600),
    )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many requests for this operation.",
        headers={"Retry-After": str(retry_after)},
    )
