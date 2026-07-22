"""Safe structured logging primitives shared by API and worker processes."""

from __future__ import annotations

import json
import logging
import re
import sys
import traceback
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from types import TracebackType
from typing import IO, Final, Literal, TypeGuard
from uuid import uuid4

type LogContextTokens = tuple[Token[str | None], Token[str | None]]

_REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)
_CORRELATION_ID: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_IDENTIFIER_PATTERN: Final = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_UUID_PATTERN: Final = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_EMAIL_PATTERN: Final = re.compile(
    r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+\b"
)
_BEARER_PATTERN: Final = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_SENSITIVE_HEADER_PATTERN: Final = re.compile(
    r"(?im)\b(authorization|cookie|set-cookie|x-api-key)\s*:\s*[^\r\n]+"
)
_SECRET_PATTERN: Final = re.compile(
    r"(?i)([\"']?(?:authorization|cookie|set-cookie|password|passwd|secret|"
    r"client[_-]?secret|access[_-]?token|refresh[_-]?token|"
    r"(?:x[-_])?api[_-]?key|session[_-]?id)[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)
_URL_CREDENTIAL_PATTERN: Final = re.compile(r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@")
_SENSITIVE_PAYLOAD_PATTERN: Final = re.compile(
    r"(?i)(features?|predictions?|request[_ -]?body|model[_ -]?artifact)"
    r"\s*[:=]\s*(\[[^\]]*\]|\{[^}]*\}|[^\s,;]+)"
)
_MAX_MESSAGE_LENGTH: Final = 2048
_PLATFORM_FIELDS: Final = (
    "method",
    "normalized_route",
    "status_code",
    "duration_ms",
    "job_name",
    "task_type",
    "algorithm",
    "trigger",
    "alert_type",
    "severity",
    "lifecycle_status",
    "attempt_number",
    "error_kind",
    "audit_event",
    "outcome",
    "reason",
    "actor_role",
    "required_roles",
    "resource_kind",
)

_configuration_lock = Lock()
_service_name = "ai-manufacturing-backend"
_environment = "local"


def is_valid_log_identifier(value: object) -> TypeGuard[str]:
    """Return whether an externally supplied context identifier is safe."""
    return isinstance(value, str) and _IDENTIFIER_PATTERN.fullmatch(value) is not None


def new_log_identifier() -> str:
    """Create a bounded opaque identifier suitable for logs and headers."""
    return str(uuid4())


def resolve_request_identifiers(
    request_id: object, correlation_id: object
) -> tuple[str, str]:
    """Validate incoming identifiers and provide safe independent fallbacks."""
    safe_request_id = (
        request_id if is_valid_log_identifier(request_id) else new_log_identifier()
    )
    safe_correlation_id = (
        correlation_id if is_valid_log_identifier(correlation_id) else safe_request_id
    )
    return safe_request_id, safe_correlation_id


def bind_log_context(
    *,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> LogContextTokens:
    """Bind validated context for the current async task or worker thread."""
    return (
        _REQUEST_ID.set(request_id if is_valid_log_identifier(request_id) else None),
        _CORRELATION_ID.set(
            correlation_id if is_valid_log_identifier(correlation_id) else None
        ),
    )


def reset_log_context(tokens: LogContextTokens) -> None:
    """Restore the previous context even after failed requests or jobs."""
    request_token, correlation_token = tokens
    _CORRELATION_ID.reset(correlation_token)
    _REQUEST_ID.reset(request_token)


def current_request_id() -> str | None:
    return _REQUEST_ID.get()


def current_correlation_id() -> str | None:
    return _CORRELATION_ID.get()


def current_trace_id() -> str | None:
    """Read trace identity only from the currently active OpenTelemetry span."""
    from app.observability.tracing import current_trace_id as active_trace_id

    return active_trace_id()


def sanitize_log_text(value: object) -> str:
    """Redact common secrets and identifiers from a bounded log message."""
    try:
        rendered = str(value)
    except Exception:
        return "log_value_unavailable"
    rendered = _URL_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]@", rendered)
    rendered = _SENSITIVE_HEADER_PATTERN.sub(
        lambda match: f"{match.group(1)}: [REDACTED]", rendered
    )
    rendered = _BEARER_PATTERN.sub("Bearer [REDACTED]", rendered)
    rendered = _SECRET_PATTERN.sub(
        lambda match: f"{match.group(1)}[REDACTED]", rendered
    )
    rendered = _SENSITIVE_PAYLOAD_PATTERN.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", rendered
    )
    rendered = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", rendered)
    rendered = _UUID_PATTERN.sub("[REDACTED_ID]", rendered)
    if len(rendered) > _MAX_MESSAGE_LENGTH:
        return f"{rendered[:_MAX_MESSAGE_LENGTH]}...[TRUNCATED]"
    return rendered


def _safe_message(record: logging.LogRecord) -> str:
    try:
        return sanitize_log_text(record.getMessage())
    except Exception:
        return "log_message_unavailable"


def _safe_exception(
    exc_info: (
        tuple[type[BaseException], BaseException, TracebackType | None]
        | tuple[None, None, None]
    ),
) -> dict[str, object] | None:
    exception_type, _exception_value, trace = exc_info
    if exception_type is None:
        return None
    result: dict[str, object] = {"type": exception_type.__name__}
    if trace is not None:
        try:
            result["stack"] = [
                {
                    "file": Path(frame.filename).name,
                    "line": frame.lineno,
                    "function": frame.name,
                }
                for frame in traceback.extract_tb(trace)[-20:]
            ]
        except Exception:
            result["stack"] = []
    return result


def _safe_field(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return sanitize_log_text(value)


def _base_payload(record: logging.LogRecord) -> dict[str, object]:
    payload: dict[str, object] = {
        "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
        "level": record.levelname,
        "logger": record.name,
        "message": _safe_message(record),
        "service": _service_name,
        "environment": _environment,
        "request_id": current_request_id(),
        "correlation_id": current_correlation_id(),
        "trace_id": current_trace_id(),
    }
    for field_name in _PLATFORM_FIELDS:
        if hasattr(record, field_name):
            payload[field_name] = _safe_field(getattr(record, field_name))
    if record.exc_info:
        safe_exception = _safe_exception(record.exc_info)
        if safe_exception is not None:
            payload["exception"] = safe_exception
    return payload


class SafeJsonFormatter(logging.Formatter):
    """Render a stable JSON schema without arbitrary ``LogRecord`` extras."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            return json.dumps(
                _base_payload(record),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        except Exception:
            return json.dumps(
                {
                    "timestamp": datetime.now(tz=UTC).isoformat(),
                    "level": "ERROR",
                    "logger": "app.observability.logging",
                    "message": "log_formatting_failed",
                    "service": _service_name,
                    "environment": _environment,
                    "request_id": None,
                    "correlation_id": None,
                    "trace_id": None,
                },
                separators=(",", ":"),
            )


class SafeTextFormatter(logging.Formatter):
    """Render the same safe schema in a human-readable local form."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            payload = _base_payload(record)
            ordered = (
                f"{payload['timestamp']} {payload['level']} {payload['logger']} "
                f"{payload['message']}"
            )
            context = " ".join(
                f"{key}={json.dumps(value, ensure_ascii=False)}"
                for key, value in payload.items()
                if key not in {"timestamp", "level", "logger", "message"}
                and value is not None
            )
            return f"{ordered} {context}".rstrip()
        except Exception:
            return "ERROR app.observability.logging log_formatting_failed"


class _PlatformStreamHandler(logging.StreamHandler[IO[str]]):
    _platform_safe_handler = True


def configure_logging(
    *,
    enabled: bool,
    log_format: Literal["json", "text"],
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    service: str,
    environment: str,
    access_logging_enabled: bool,
    stream: IO[str] | None = None,
) -> None:
    """Install one process-wide safe handler and suppress duplicate access logs."""
    global _environment, _service_name
    _ = access_logging_enabled
    formatter: logging.Formatter
    formatter = (
        SafeJsonFormatter() if enabled and log_format == "json" else SafeTextFormatter()
    )
    with _configuration_lock:
        _service_name = service
        _environment = environment
        root_logger = logging.getLogger()
        for existing_handler in tuple(root_logger.handlers):
            is_pytest_handler = existing_handler.__class__.__module__.startswith(
                "_pytest."
            )
            if (
                getattr(existing_handler, "_platform_safe_handler", False)
                or not is_pytest_handler
            ):
                root_logger.removeHandler(existing_handler)

        handler = _PlatformStreamHandler(stream if stream is not None else sys.stdout)
        handler.setFormatter(formatter)
        handler.setLevel(log_level)
        root_logger.addHandler(handler)
        root_logger.setLevel(log_level)

        for logger_name in (
            "app.access",
            "app.security.audit",
            "app.worker",
            "uvicorn",
            "uvicorn.error",
            "dramatiq",
        ):
            named_logger = logging.getLogger(logger_name)
            named_logger.handlers.clear()
            named_logger.setLevel(logging.NOTSET)
            named_logger.propagate = True
            named_logger.disabled = False

        access_logger = logging.getLogger("uvicorn.access")
        access_logger.handlers.clear()
        access_logger.propagate = False
        access_logger.disabled = True
        logging.disable(logging.NOTSET)
        logging.raiseExceptions = False


def emit_safe(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    extra: dict[str, object] | None = None,
    exc_info: (
        bool | tuple[type[BaseException], BaseException, TracebackType | None]
    ) = False,
) -> None:
    """Emit an allowlisted record without allowing logging to break business work."""
    safe_extra = {
        key: value for key, value in (extra or {}).items() if key in _PLATFORM_FIELDS
    }
    try:
        logger.log(level, message, extra=safe_extra, exc_info=exc_info)
    except Exception:
        return
