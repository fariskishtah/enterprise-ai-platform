"""Administrative command for bounded stale-running job recovery."""

import asyncio

from app.config.settings import get_settings
from app.db.session import build_session_factory
from app.ml.jobs.queue import DramatiqTrainingJobQueue
from app.ml.jobs.service import StaleTrainingJobRecoveryService
from app.repositories.ai_governance import TrainingJobRepository


async def _reconcile() -> tuple[str, ...]:
    settings = get_settings()
    session_factory = build_session_factory(settings.database_url)
    async with session_factory() as session:
        service = StaleTrainingJobRecoveryService(
            repository=TrainingJobRepository(session),
            queue=DramatiqTrainingJobQueue(),
            stale_after_seconds=settings.training_job_stale_after_seconds,
            orphaned_after_seconds=settings.training_job_orphaned_after_seconds,
        )
        recovered = await service.reconcile()
    return tuple(str(job_id) for job_id in recovered)


def main() -> None:
    """Recover stale running and aged orphaned queued jobs by stable UUID."""
    for job_id in asyncio.run(_reconcile()):
        print(job_id)


if __name__ == "__main__":
    main()
