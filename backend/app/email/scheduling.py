"""Email-specific scheduler type for worker-local reconciliation."""

from app.ml.jobs.automl_scheduling import AutoMLReconciliationSchedulerMiddleware


class EmailReconciliationSchedulerMiddleware(AutoMLReconciliationSchedulerMiddleware):
    """Keep email scheduling distinct from other reconciliation middleware."""
