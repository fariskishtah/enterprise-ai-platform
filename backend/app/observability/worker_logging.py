"""Dramatiq correlation propagation and bounded worker lifecycle logging."""

from __future__ import annotations

import logging
import re
from contextvars import Token
from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from typing import Any, Final

from dramatiq import Message
from dramatiq.broker import Broker, MessageProxy
from dramatiq.middleware import Middleware
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.context import Context as OtelContext
from opentelemetry.trace import Span, SpanKind

from app.config.settings import LogFormat, LogLevel
from app.observability.logging import (
    LogContextTokens,
    bind_log_context,
    configure_logging,
    current_correlation_id,
    emit_safe,
    is_valid_log_identifier,
    new_log_identifier,
    reset_log_context,
)
from app.observability.tracing import (
    TracingConfig,
    configure_tracing,
    extract_w3c_trace_context,
    inject_w3c_trace_context,
    record_safe_span_error,
)

logger = logging.getLogger("app.worker")

_ACTOR_JOB_NAMES = {
    "execute_training_job": "training",
    "execute_scheduled_monitoring": "monitoring_evaluation",
    "execute_prediction_event_retention": "prediction_event_retention",
    "execute_monitoring_evaluation_retention": "monitoring_evaluation_retention",
    "execute_reference_profile_reconciliation": "reference_profile_reconciliation",
    "execute_retraining_reconciliation": "retraining_reconciliation",
    "execute_stale_alert_reconciliation": "stale_alert_reconciliation",
}
_TRACE_CONTEXT_OPTION: Final = "otel_trace_context"
_TRACEPARENT_PATTERN: Final = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")
_TRACESTATE_PATTERN: Final = re.compile(r"^[\x20-\x7e]{1,512}$")


def worker_job_name(actor_name: str) -> str | None:
    """Map an actor to the fixed low-cardinality job vocabulary."""
    return _ACTOR_JOB_NAMES.get(actor_name)


def _attempt_number(message: MessageProxy) -> int:
    retries = message.options.get("retries", 0)
    if not isinstance(retries, int) or isinstance(retries, bool):
        return 1
    return min(max(retries, 0), 99) + 1


@dataclass(frozen=True)
class _WorkerLogState:
    started: float
    tokens: LogContextTokens
    job_name: str
    attempt_number: int
    span: Span
    context_token: Token[OtelContext]


class WorkerLoggingMiddleware(Middleware):
    """Propagate independent correlation and W3C contexts for known actors."""

    def __init__(
        self,
        *,
        enabled: bool,
        log_format: LogFormat,
        log_level: LogLevel,
        service: str,
        environment: str,
        tracing_config: TracingConfig | None = None,
    ) -> None:
        self._enabled = enabled
        self._log_format = log_format
        self._log_level = log_level
        self._service = service
        self._environment = environment
        self._tracing_config = tracing_config
        self._active: dict[str, _WorkerLogState] = {}
        self._lock = Lock()

    def before_enqueue(self, broker: Broker, message: Message[Any], delay: int) -> None:
        _ = (broker, delay)
        existing = message.options.get("correlation_id")
        if not is_valid_log_identifier(existing):
            message.options["correlation_id"] = (
                current_correlation_id() or new_log_identifier()
            )

        job_name = worker_job_name(message.actor_name)
        if job_name is None:
            return
        existing_trace_context = _safe_trace_carrier(
            message.options.get(_TRACE_CONTEXT_OPTION)
        )
        if existing_trace_context:
            return
        carrier: dict[str, str] = {}
        inject_w3c_trace_context(carrier)
        safe_carrier = _safe_trace_carrier(carrier)
        if safe_carrier:
            message.options[_TRACE_CONTEXT_OPTION] = safe_carrier
        else:
            message.options.pop(_TRACE_CONTEXT_OPTION, None)

    def after_process_boot(self, broker: Broker) -> None:
        _ = broker
        configure_logging(
            enabled=self._enabled,
            log_format=self._log_format,
            log_level=self._log_level,
            service=self._service,
            environment=self._environment,
            access_logging_enabled=False,
        )
        if self._tracing_config is not None:
            configure_tracing(self._tracing_config)

    def before_process_message(self, broker: Broker, message: MessageProxy) -> None:
        _ = broker
        job_name = worker_job_name(message.actor_name)
        if job_name is None:
            return
        correlation_id = message.options.get("correlation_id")
        safe_correlation_id = (
            correlation_id
            if is_valid_log_identifier(correlation_id)
            else new_log_identifier()
        )
        parent_context = extract_w3c_trace_context(
            _safe_trace_carrier(message.options.get(_TRACE_CONTEXT_OPTION))
        )
        span = trace.get_tracer("ai-manufacturing-platform").start_span(
            f"dramatiq {job_name} process",
            context=parent_context,
            kind=SpanKind.CONSUMER,
            attributes={
                "messaging.system": "dramatiq",
                "messaging.operation.type": "process",
                "messaging.destination.name": job_name,
            },
            record_exception=False,
            set_status_on_exception=False,
        )
        context_token = otel_context.attach(trace.set_span_in_context(span))
        try:
            tokens = bind_log_context(correlation_id=safe_correlation_id)
        except BaseException:
            otel_context.detach(context_token)
            span.end()
            raise
        state = _WorkerLogState(
            started=perf_counter(),
            tokens=tokens,
            job_name=job_name,
            attempt_number=_attempt_number(message),
            span=span,
            context_token=context_token,
        )
        with self._lock:
            self._active[message.message_id] = state
        emit_safe(
            logger,
            logging.INFO,
            "background_job_lifecycle",
            extra={
                "job_name": job_name,
                "lifecycle_status": "started",
                "attempt_number": state.attempt_number,
            },
        )

    def after_process_message(
        self,
        broker: Broker,
        message: MessageProxy,
        *,
        result: Any | None = None,
        exception: BaseException | None = None,
    ) -> None:
        _ = (broker, result)
        self._finish(message, exception=exception, lifecycle_status=None)

    def after_skip_message(self, broker: Broker, message: MessageProxy) -> None:
        _ = broker
        self._finish(message, exception=None, lifecycle_status="skipped")

    def _finish(
        self,
        message: MessageProxy,
        *,
        exception: BaseException | None,
        lifecycle_status: str | None,
    ) -> None:
        with self._lock:
            state = self._active.pop(message.message_id, None)
        if state is None:
            return
        final_status = lifecycle_status or (
            "failed" if exception is not None else "completed"
        )
        exc_info = (
            (type(exception), exception, exception.__traceback__)
            if exception is not None
            else False
        )
        try:
            if exception is not None:
                record_safe_span_error(state.span, exception)
            emit_safe(
                logger,
                logging.ERROR if exception is not None else logging.INFO,
                "background_job_lifecycle",
                extra={
                    "job_name": state.job_name,
                    "lifecycle_status": final_status,
                    "attempt_number": state.attempt_number,
                    "duration_ms": round((perf_counter() - state.started) * 1000, 3),
                    "error_kind": (
                        type(exception).__name__ if exception is not None else None
                    ),
                },
                exc_info=exc_info,
            )
        finally:
            reset_log_context(state.tokens)
            otel_context.detach(state.context_token)
            state.span.end()


def _safe_trace_carrier(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    traceparent = value.get("traceparent")
    if (
        not isinstance(traceparent, str)
        or _TRACEPARENT_PATTERN.fullmatch(traceparent) is None
    ):
        return {}
    carrier = {"traceparent": traceparent}
    tracestate = value.get("tracestate")
    if isinstance(tracestate, str) and _TRACESTATE_PATTERN.fullmatch(tracestate):
        carrier["tracestate"] = tracestate
    return carrier
