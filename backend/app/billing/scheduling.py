"""Distinct worker-local schedulers for durable billing maintenance."""

from app.ml.jobs.automl_scheduling import AutoMLReconciliationSchedulerMiddleware


class BillingLifecycleSchedulerMiddleware(AutoMLReconciliationSchedulerMiddleware):
    """Schedule authoritative subscription timestamp reconciliation."""


class BillingWebhookRecoverySchedulerMiddleware(
    AutoMLReconciliationSchedulerMiddleware
):
    """Schedule stale durable webhook recovery and dead-letter detection."""


class BillingProviderReconciliationSchedulerMiddleware(
    AutoMLReconciliationSchedulerMiddleware
):
    """Schedule exact provider inquiry for aged unresolved payments."""
