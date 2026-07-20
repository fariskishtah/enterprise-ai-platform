"""Pure ASGI request context and privacy-preserving access completion logging."""

from __future__ import annotations

import logging
from contextlib import suppress
from time import perf_counter

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.http import normalized_route
from app.observability.logging import (
    bind_log_context,
    emit_safe,
    reset_log_context,
    resolve_request_identifiers,
)

logger = logging.getLogger("app.access")


class RequestContextLoggingMiddleware:
    """Bind safe IDs, return them as headers, and log one bounded completion."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        request_id_header: str,
        correlation_id_header: str,
        access_logging_enabled: bool,
        excluded_paths: frozenset[str],
    ) -> None:
        self._app = app
        self._request_id_header = request_id_header
        self._correlation_id_header = correlation_id_header
        self._access_logging_enabled = access_logging_enabled
        self._excluded_paths = excluded_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id, correlation_id = resolve_request_identifiers(
            headers.get(self._request_id_header),
            headers.get(self._correlation_id_header),
        )
        tokens = bind_log_context(
            request_id=request_id,
            correlation_id=correlation_id,
        )
        method = str(scope.get("method", "UNKNOWN")).upper()
        started = perf_counter()
        status_code = 500

        async def send_with_context(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_headers = MutableHeaders(scope=message)
                response_headers[self._request_id_header] = request_id
                response_headers[self._correlation_id_header] = correlation_id
            await send(message)

        try:
            await self._app(scope, receive, send_with_context)
        finally:
            try:
                if (
                    self._access_logging_enabled
                    and scope.get("path") not in self._excluded_paths
                ):
                    with suppress(Exception):
                        emit_safe(
                            logger,
                            logging.INFO,
                            "http_request_completed",
                            extra={
                                "method": method,
                                "normalized_route": normalized_route(scope),
                                "status_code": status_code,
                                "duration_ms": round(
                                    (perf_counter() - started) * 1000, 3
                                ),
                            },
                        )
            finally:
                reset_log_context(tokens)
