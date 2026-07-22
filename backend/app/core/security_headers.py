"""Security response headers for API and authentication traffic."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_CSP_EXCLUDED_PATHS = frozenset({"/docs", "/openapi.json", "/redoc"})
_SENSITIVE_NO_STORE_PREFIXES = (
    "/auth",
    "/ai",
    "/companies",
    "/experiments",
    "/factories",
    "/feature-datasets",
    "/machines",
    "/model-artifacts",
    "/sensor-readings",
    "/sensors",
    "/training-runs",
    "/upload-jobs",
    "/users",
)


class SecurityHeadersMiddleware:
    """Apply browser hardening without blocking the development API docs."""

    def __init__(self, app: ASGIApp, *, enable_hsts: bool = False) -> None:
        self._app = app
        self._enable_hsts = enable_hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path = str(scope.get("path", ""))

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Permissions-Policy"] = (
                    "camera=(), geolocation=(), microphone=()"
                )
                if self._enable_hsts:
                    headers["Strict-Transport-Security"] = (
                        "max-age=31536000; includeSubDomains"
                    )
                if path not in _CSP_EXCLUDED_PATHS:
                    headers["Content-Security-Policy"] = (
                        "default-src 'none'; frame-ancestors 'none'; "
                        "base-uri 'none'; form-action 'none'"
                    )
                if _requires_no_store(path):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self._app(scope, receive, send_with_security_headers)


def _requires_no_store(path: str) -> bool:
    """Identify sensitive API namespaces without accepting prefix lookalikes."""
    return any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in _SENSITIVE_NO_STORE_PREFIXES
    )
