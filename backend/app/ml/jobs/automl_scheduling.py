"""Bounded worker-local scheduling for idempotent AutoML reconciliation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import suppress
from threading import Event, Thread
from typing import Protocol

from dramatiq import Middleware
from redis import Redis
from redis.exceptions import RedisError

from app.observability.logging import emit_safe

AUTOML_RECONCILIATION_SCHEDULER_KEY = "scheduler:automl:reconciliation:v1"
logger = logging.getLogger(__name__)


class SchedulerRedisClient(Protocol):
    def set(self, name: str, value: str, *, ex: int, nx: bool) -> object: ...

    def close(self) -> object: ...


class AutoMLReconciliationSchedulerMiddleware(Middleware):
    """Enqueue one reconciliation pass per interval across worker replicas."""

    def __init__(
        self,
        *,
        enabled: bool,
        interval_seconds: int,
        redis_url: str,
        enqueue: Callable[[], object],
        redis_client: SchedulerRedisClient | None = None,
    ) -> None:
        self._enabled = enabled
        self._interval_seconds = interval_seconds
        self._client = redis_client or Redis.from_url(redis_url, decode_responses=True)
        self._enqueue = enqueue
        self._stop = Event()
        self._thread: Thread | None = None

    def after_worker_boot(self, broker: object, worker: object) -> None:
        del broker, worker
        if not self._enabled:
            return
        self._stop.clear()
        self._thread = Thread(
            target=self._run,
            name="automl-reconciliation-scheduler",
            daemon=True,
        )
        self._thread.start()

    def before_worker_shutdown(self, broker: object, worker: object) -> None:
        del broker, worker
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=min(self._interval_seconds + 1, 10))
        self._client.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                acquired = self._client.set(
                    AUTOML_RECONCILIATION_SCHEDULER_KEY,
                    "scheduled",
                    ex=self._interval_seconds,
                    nx=True,
                )
                if acquired:
                    self._enqueue()
            except RedisError:
                emit_safe(
                    logger,
                    logging.ERROR,
                    "automl_reconciliation_schedule_failed",
                    extra={"error_kind": "redis_unavailable"},
                )
            except Exception:
                emit_safe(
                    logger,
                    logging.ERROR,
                    "automl_reconciliation_enqueue_failed",
                    extra={"error_kind": "queue_unavailable"},
                    exc_info=True,
                )
            self._stop.wait(self._interval_seconds)

        with suppress(RedisError):
            self._client.close()
