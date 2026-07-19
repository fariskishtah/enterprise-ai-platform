"""Pure ASGI HTTP metrics middleware and unauthenticated exposition response."""

from __future__ import annotations

import logging
from time import perf_counter

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.metrics import (
    record_http_request_completed,
    record_http_request_started,
)

logger = logging.getLogger(__name__)


class PrometheusMetricsMiddleware:
    """Record normalized route-template HTTP metrics without request payloads."""

    def __init__(self, app: ASGIApp, *, excluded_paths: frozenset[str]) -> None:
        self._app = app
        self._excluded_paths = excluded_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self._excluded_paths:
            await self._app(scope, receive, send)
            return

        method = str(scope.get("method", "UNKNOWN")).upper()
        started = perf_counter()
        status_code = 500
        record_http_request_started(method=method)

        async def observe_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self._app(scope, receive, observe_status)
        finally:
            record_http_request_completed(
                method=method,
                route=_normalized_route(scope),
                status_code=status_code,
                duration_seconds=perf_counter() - started,
            )


def metrics_response(_request: Request) -> Response:
    """Render the process registry without authentication or application data."""
    try:
        payload = generate_latest()
    except Exception:
        logger.error("observability_metrics_render_failed")
        return Response(status_code=503)
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)


def _normalized_route(scope: Scope) -> str:
    route = scope.get("route")
    if isinstance(route, BaseRoute):
        path = getattr(route, "path", None)
        if isinstance(path, str) and path.startswith("/"):
            return path
    return "unmatched"
