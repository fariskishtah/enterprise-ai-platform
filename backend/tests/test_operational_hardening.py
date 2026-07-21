"""Focused distributed limiting and worker-operational tests."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.config.settings import Settings
from app.dependencies.operational import OperationalProbe
from app.dependencies.rate_limit import enforce_mutation_rate_limit
from fastapi import HTTPException
from redis.exceptions import ConnectionError as RedisConnectionError
from starlette.requests import Request


class MemoryStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.counts: dict[str, int] = {}
        self.fail = fail

    async def increment(self, key: str, window_seconds: int) -> tuple[int, int]:
        if self.fail:
            raise RedisConnectionError("private redis detail")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key], min(window_seconds, 41)


def mutation_request(path: str = "/ai/predictions/random-forest/regression") -> Request:
    return Request({"type": "http", "method": "POST", "path": path, "headers": []})


@pytest.mark.anyio
async def test_authenticated_mutation_limit_is_private_bounded_and_user_scoped(
    settings: Settings,
) -> None:
    limited = settings.model_copy(
        update={
            "mutation_rate_limit_enabled": True,
            "mutation_rate_limit_requests": 1,
            "mutation_rate_limit_window_seconds": 60,
        }
    )
    store = MemoryStore()
    first_user_id = uuid4()
    first_user = SimpleNamespace(id=first_user_id)
    second_user = SimpleNamespace(id=uuid4())

    await enforce_mutation_rate_limit(mutation_request(), first_user, limited, store)  # type: ignore[arg-type]
    await enforce_mutation_rate_limit(mutation_request(), second_user, limited, store)  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as caught:
        await enforce_mutation_rate_limit(  # type: ignore[arg-type]
            mutation_request(), first_user, limited, store
        )

    assert caught.value.status_code == 429
    assert caught.value.detail == "Too many requests for this operation."
    assert caught.value.headers == {"Retry-After": "41"}
    assert len(store.counts) == 2
    assert all(str(first_user_id) not in key for key in store.counts)
    assert all("predictions" not in key for key in store.counts)


@pytest.mark.anyio
async def test_authenticated_mutation_limit_fails_closed_without_redis(
    settings: Settings,
) -> None:
    with pytest.raises(HTTPException) as caught:
        await enforce_mutation_rate_limit(  # type: ignore[arg-type]
            mutation_request(),
            SimpleNamespace(id=uuid4()),
            settings.model_copy(update={"mutation_rate_limit_enabled": True}),
            MemoryStore(fail=True),
        )

    assert caught.value.status_code == 503
    assert caught.value.detail == "A required service is unavailable."
    assert "redis" not in str(caught.value.detail).lower()


class FakeRedis:
    def __init__(
        self,
        *,
        heartbeat: str | None = "available",
        fail: bool = False,
    ) -> None:
        self.heartbeat = heartbeat
        self.fail = fail

    async def ping(self) -> bool:
        if self.fail:
            raise RedisConnectionError("private redis detail")
        return True

    async def get(self, key: str) -> str | None:
        del key
        return self.heartbeat


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("redis", "expected"),
    [
        (FakeRedis(), ("available", "available", "available")),
        (FakeRedis(heartbeat=None), ("available", "available", "unavailable")),
        (FakeRedis(fail=True), ("unavailable", "unavailable", "unknown")),
    ],
)
async def test_operational_probe_distinguishes_worker_from_redis(
    redis: FakeRedis,
    expected: tuple[str, str, str],
) -> None:
    probe = OperationalProbe("redis://unused:6379/0")
    probe._redis = redis  # type: ignore[assignment]

    assert await probe.queue_and_worker() == expected
