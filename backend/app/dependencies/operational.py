"""Safe Redis, queue, and worker operational probes."""

from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config.settings import Settings, get_settings
from app.observability.worker_heartbeat import TRAINING_WORKER_HEARTBEAT_KEY

Availability = Literal["available", "unavailable", "unknown"]


class OperationalProbe:
    """Probe bounded dependency signals without exposing connection details."""

    def __init__(self, redis_url: str) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)

    async def queue_and_worker(self) -> tuple[Availability, Availability, Availability]:
        try:
            await self._redis.ping()
            heartbeat = await self._redis.get(TRAINING_WORKER_HEARTBEAT_KEY)
        except RedisError:
            return "unavailable", "unavailable", "unknown"
        worker: Availability = (
            "available" if heartbeat == "available" else "unavailable"
        )
        return "available", "available", worker


@lru_cache
def _operational_probe(redis_url: str) -> OperationalProbe:
    return OperationalProbe(redis_url)


def get_operational_probe(
    settings: Annotated[Settings, Depends(get_settings)],
) -> OperationalProbe:
    return _operational_probe(settings.redis_url)


async def require_training_worker_available(
    probe: Annotated[OperationalProbe, Depends(get_operational_probe)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Reject queued work unless Redis, the queue, and a real worker are available."""
    if not settings.worker_availability_check_enabled:
        return
    redis, queue, worker = await probe.queue_and_worker()
    if (redis, queue, worker) != ("available", "available", "available"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background processing is temporarily unavailable.",
        )
