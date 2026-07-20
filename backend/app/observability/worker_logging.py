"""Dramatiq correlation propagation and bounded worker lifecycle logging."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from typing import Any

from dramatiq import Message
from dramatiq.broker import Broker, MessageProxy
from dramatiq.middleware import Middleware

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


class WorkerLoggingMiddleware(Middleware):
    """Propagate only correlation IDs and log each known actor lifecycle."""

    def __init__(
        self,
        *,
        enabled: bool,
        log_format: LogFormat,
        log_level: LogLevel,
        service: str,
        environment: str,
    ) -> None:
        self._enabled = enabled
        self._log_format = log_format
        self._log_level = log_level
        self._service = service
        self._environment = environment
        self._active: dict[str, _WorkerLogState] = {}
        self._lock = Lock()

    def before_enqueue(self, broker: Broker, message: Message[Any], delay: int) -> None:
        _ = (broker, delay)
        existing = message.options.get("correlation_id")
        if is_valid_log_identifier(existing):
            return
        message.options["correlation_id"] = (
            current_correlation_id() or new_log_identifier()
        )

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
        tokens = bind_log_context(correlation_id=safe_correlation_id)
        state = _WorkerLogState(
            started=perf_counter(),
            tokens=tokens,
            job_name=job_name,
            attempt_number=_attempt_number(message),
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
