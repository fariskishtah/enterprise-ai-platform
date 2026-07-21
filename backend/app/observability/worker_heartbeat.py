"""Expiring Redis heartbeat emitted by the real Dramatiq worker process."""

from __future__ import annotations

import logging
from contextlib import suppress
from threading import Event, Thread

from dramatiq import Middleware
from redis import Redis
from redis.exceptions import RedisError

from app.observability.logging import emit_safe

TRAINING_WORKER_HEARTBEAT_KEY = "operational:worker:training:v1"
logger = logging.getLogger(__name__)


class WorkerHeartbeatMiddleware(Middleware):
    """Maintain a category-only heartbeat without infrastructure identifiers."""

    def __init__(
        self,
        *,
        redis_url: str,
        interval_seconds: int,
        ttl_seconds: int,
    ) -> None:
        self._client = Redis.from_url(redis_url, decode_responses=True)
        self._interval_seconds = interval_seconds
        self._ttl_seconds = ttl_seconds
        self._stop = Event()
        self._thread: Thread | None = None

    def after_worker_boot(self, broker: object, worker: object) -> None:
        del broker, worker
        self._stop.clear()
        self._thread = Thread(
            target=self._run,
            name="training-worker-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def before_worker_shutdown(self, broker: object, worker: object) -> None:
        del broker, worker
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval_seconds + 1)
        with suppress(RedisError):
            self._client.delete(TRAINING_WORKER_HEARTBEAT_KEY)
        self._client.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._client.set(
                    TRAINING_WORKER_HEARTBEAT_KEY,
                    "available",
                    ex=self._ttl_seconds,
                )
            except RedisError:
                emit_safe(
                    logger,
                    logging.ERROR,
                    "worker_heartbeat_failed",
                    extra={"error_kind": "redis_unavailable"},
                )
            self._stop.wait(self._interval_seconds)
