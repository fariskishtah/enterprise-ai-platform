"""Streaming request-body limits enforced before application parsing."""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Reject oversized HTTP bodies without buffering unbounded input."""

    def __init__(self, app: ASGIApp, *, maximum_bytes: int) -> None:
        if maximum_bytes <= 0:
            raise ValueError("maximum_bytes must be positive.")
        self._app = app
        self._maximum_bytes = maximum_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        content_length = _content_length(scope)
        if content_length is not None and content_length > self._maximum_bytes:
            await _send_too_large(send)
            return

        received = 0

        async def bounded_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] != "http.request":
                return message
            body = message.get("body", b"")
            received += len(body)
            if received > self._maximum_bytes:
                raise _RequestBodyTooLarge
            return message

        started = False

        async def bounded_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self._app(scope, bounded_receive, bounded_send)
        except _RequestBodyTooLarge:
            if not started:
                await _send_too_large(send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name.lower() != b"content-length":
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return max(parsed, 0)
    return None


async def _send_too_large(send: Send) -> None:
    body = json.dumps(
        {"detail": "The request body exceeds the configured size limit."},
        separators=(",", ":"),
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
