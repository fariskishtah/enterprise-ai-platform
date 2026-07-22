"""AutoML reconciliation scheduler registration and replica fencing tests."""

from threading import Event

from app.ml.jobs.automl_scheduling import AutoMLReconciliationSchedulerMiddleware


class FakeRedis:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired
        self.closed = False

    def set(self, *_args: object, **_kwargs: object) -> bool:
        return self.acquired

    def close(self) -> None:
        self.closed = True


def test_scheduler_enqueues_after_distributed_lock() -> None:
    queued = Event()
    client = FakeRedis(acquired=True)
    middleware = AutoMLReconciliationSchedulerMiddleware(
        enabled=True,
        enqueue=lambda: queued.set(),
        interval_seconds=10,
        redis_client=client,
        redis_url="redis://local-test",
    )
    middleware.after_worker_boot(object(), object())
    assert queued.wait(timeout=1)
    middleware.before_worker_shutdown(object(), object())
    assert client.closed


def test_scheduler_does_not_enqueue_without_distributed_lock() -> None:
    queued = Event()
    client = FakeRedis(acquired=False)
    middleware = AutoMLReconciliationSchedulerMiddleware(
        enabled=True,
        enqueue=lambda: queued.set(),
        interval_seconds=10,
        redis_client=client,
        redis_url="redis://local-test",
    )
    middleware.after_worker_boot(object(), object())
    middleware.before_worker_shutdown(object(), object())
    assert not queued.is_set()
