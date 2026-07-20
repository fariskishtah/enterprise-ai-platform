"""Dramatiq hooks for internal worker exposition and actor failure metrics."""

from __future__ import annotations

import logging
from typing import Any

from dramatiq.broker import Broker, MessageProxy
from dramatiq.middleware import Middleware
from prometheus_client import start_http_server

from app.observability.metrics import (
    configure_metrics,
    record_background_job_failure,
    record_background_job_processed,
)
from app.observability.worker_logging import worker_job_name

logger = logging.getLogger(__name__)


class WorkerPrometheusMiddleware(Middleware):
    """Start one internal scrape listener per configured worker process."""

    def __init__(
        self, *, enabled: bool, service: str, environment: str, port: int
    ) -> None:
        self._enabled = enabled
        self._service = service
        self._environment = environment
        self._port = port
        self._server: Any | None = None
        self._thread: Any | None = None

    def after_process_boot(self, broker: Broker) -> None:
        _ = broker
        configure_metrics(
            enabled=self._enabled,
            service=self._service,
            environment=self._environment,
        )
        if not self._enabled:
            return
        try:
            self._server, self._thread = start_http_server(port=self._port)
        except Exception:
            logger.warning(
                "observability_worker_metrics_listener_failed port=%s",
                self._port,
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
        job_name = worker_job_name(message.actor_name)
        if job_name is None:
            return
        final_status = "failed" if exception is not None else "completed"
        record_background_job_processed(
            job_name=job_name,
            final_status=final_status,
        )
        if exception is not None:
            record_background_job_failure(job_name=job_name)

    def after_skip_message(self, broker: Broker, message: MessageProxy) -> None:
        _ = broker
        job_name = worker_job_name(message.actor_name)
        if job_name is not None:
            record_background_job_processed(
                job_name=job_name,
                final_status="skipped",
            )
