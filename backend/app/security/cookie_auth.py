"""Refresh-cookie issuance and request validation."""

from __future__ import annotations

import hmac
import secrets

from fastapi import HTTPException, Request, Response, status

from app.config.settings import Settings

# The public reverse proxy exposes backend auth routes below `/api/auth`, while
# direct development clients use `/auth`. A same-origin root path is therefore
# required for one cookie contract to work through both supported ingress paths.
REFRESH_COOKIE_PATH = "/"
CSRF_COOKIE_PATH = "/"
CSRF_HEADER = "X-CSRF-Token"
REFRESH_COOKIE_NAME = "factorymind_refresh"
CSRF_COOKIE_NAME = "factorymind_csrf"


def issue_auth_cookies(
    response: Response, *, refresh_token: str, settings: Settings
) -> None:
    """Set a protected refresh cookie and readable double-submit CSRF cookie."""
    max_age = settings.refresh_token_expire_days * 24 * 60 * 60
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        httponly=True,
        path=REFRESH_COOKIE_PATH,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=max_age,
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        secrets.token_urlsafe(32),
        httponly=False,
        path=CSRF_COOKIE_PATH,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=max_age,
    )


def clear_auth_cookies(response: Response, *, settings: Settings) -> None:
    """Expire both authentication cookies with their original attributes."""
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )
    response.delete_cookie(
        CSRF_COOKIE_NAME,
        path=CSRF_COOKIE_PATH,
        httponly=False,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )


def require_cookie_auth(request: Request, *, settings: Settings) -> str:
    """Validate request origin and double-submit token, then return refresh JWT."""
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in settings.cors_allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not allowed.",
        )
    cookie_csrf = request.cookies.get(CSRF_COOKIE_NAME)
    header_csrf = request.headers.get(CSRF_HEADER)
    if (
        not cookie_csrf
        or not header_csrf
        or not hmac.compare_digest(cookie_csrf, header_csrf)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed.",
        )
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh session is missing.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return refresh_token
