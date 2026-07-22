"""UUID-only Dramatiq transport boundary for AutoML execution."""

from typing import Protocol
from uuid import UUID

from app.observability.tracing import start_dramatiq_producer_span


class AutoMLQueue(Protocol):
    def enqueue_study(self, study_id: UUID) -> str: ...

    def enqueue_trial(self, trial_id: UUID) -> str: ...


class DramatiqAutoMLQueue:
    def enqueue_study(self, study_id: UUID) -> str:
        from app.ml.jobs.tasks import coordinate_automl_study

        with start_dramatiq_producer_span("automl-study"):
            return coordinate_automl_study.send(str(study_id)).message_id

    def enqueue_trial(self, trial_id: UUID) -> str:
        from app.ml.jobs.tasks import execute_automl_trial

        with start_dramatiq_producer_span("automl-trial"):
            return execute_automl_trial.send(str(trial_id)).message_id
