"""Failure-isolated Prometheus metrics with bounded label vocabularies."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)

_HTTP_DURATION_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)
_JOB_DURATION_BUCKETS = (0.1, 0.5, 1.0, 5.0, 15.0, 30.0, 60.0, 300.0, 900.0)
_EVALUATION_DURATION_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 15.0, 30.0)

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Completed backend HTTP requests.",
    ("service", "environment", "method", "route", "status_code"),
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Backend HTTP request duration in seconds.",
    ("service", "environment", "method", "route"),
    buckets=_HTTP_DURATION_BUCKETS,
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Backend HTTP requests currently in progress.",
    ("service", "environment", "method"),
)

TRAINING_JOBS_SUBMITTED = Counter(
    "training_jobs_submitted_total",
    "Durably submitted background training jobs.",
    ("service", "environment", "task_type", "algorithm"),
)
TRAINING_JOBS_COMPLETED = Counter(
    "training_jobs_completed_total",
    "Successfully completed background training jobs.",
    ("service", "environment", "task_type", "algorithm", "final_status"),
)
TRAINING_JOBS_FAILED = Counter(
    "training_jobs_failed_total",
    "Terminally failed background training jobs.",
    ("service", "environment", "task_type", "algorithm", "final_status"),
)
TRAINING_JOB_DURATION = Histogram(
    "training_job_duration_seconds",
    "Terminal background training job attempt duration in seconds.",
    ("service", "environment", "task_type", "algorithm", "final_status"),
    buckets=_JOB_DURATION_BUCKETS,
)

PREDICTION_REQUESTS = Counter(
    "prediction_requests_total",
    "Registered-model prediction requests.",
    ("service", "environment", "task_type", "algorithm", "final_status"),
)
PREDICTION_ROWS = Counter(
    "prediction_rows_total",
    "Rows submitted to registered-model prediction.",
    ("service", "environment", "task_type", "algorithm", "final_status"),
)
PREDICTION_FAILURES = Counter(
    "prediction_failures_total",
    "Failed registered-model prediction requests.",
    ("service", "environment", "task_type", "algorithm"),
)

MONITORING_EVALUATIONS = Counter(
    "monitoring_evaluations_total",
    "Completed or failed monitoring evaluation attempts.",
    ("service", "environment", "trigger", "final_status"),
)
MONITORING_EVALUATION_DURATION = Histogram(
    "monitoring_evaluation_duration_seconds",
    "Monitoring evaluation attempt duration in seconds.",
    ("service", "environment", "trigger", "final_status"),
    buckets=_EVALUATION_DURATION_BUCKETS,
)
MONITORING_ALERTS_CREATED = Counter(
    "monitoring_alerts_created_total",
    "New internal monitoring alerts created after deduplication.",
    ("service", "environment", "alert_type", "severity"),
)
MONITORING_ALERTS_RESOLVED = Counter(
    "monitoring_alerts_resolved_total",
    "Internal monitoring alerts transitioned to resolved.",
    ("service", "environment", "alert_type", "severity"),
)

RETRAINING_REQUESTS = Counter(
    "retraining_requests_total",
    "New governed retraining requests persisted.",
    ("service", "environment", "trigger"),
)
RETRAINING_REQUESTS_BLOCKED = Counter(
    "retraining_requests_blocked_total",
    "Controlled retraining decisions blocked by governance.",
    ("service", "environment", "trigger", "final_status"),
)
BACKGROUND_JOB_FAILURES = Counter(
    "background_job_failures_total",
    "Dramatiq actor executions that raised an exception.",
    ("service", "environment", "job_name"),
)
BACKGROUND_JOBS_PROCESSED = Counter(
    "background_jobs_processed_total",
    "Dramatiq actor executions that reached a bounded terminal outcome.",
    ("service", "environment", "job_name", "final_status"),
)


@dataclass(frozen=True, slots=True)
class _MetricsContext:
    enabled: bool
    service: str
    environment: str


_context = _MetricsContext(False, "unconfigured", "local")
_context_lock = Lock()


def configure_metrics(*, enabled: bool, service: str, environment: str) -> None:
    """Configure the process-local bounded labels used by every recorder."""
    global _context
    with _context_lock:
        _context = _MetricsContext(enabled, service, environment)


def record_http_request_started(*, method: str) -> None:
    labels = _base_labels()
    _safe_record(
        "http_requests_in_progress",
        lambda: HTTP_REQUESTS_IN_PROGRESS.labels(
            **labels,
            method=method,
        ).inc(),
    )


def record_http_request_completed(
    *, method: str, route: str, status_code: int, duration_seconds: float
) -> None:
    labels = _base_labels()
    _safe_record(
        "http_requests_total",
        lambda: HTTP_REQUESTS.labels(
            **labels,
            method=method,
            route=route,
            status_code=str(status_code),
        ).inc(),
    )
    _safe_record(
        "http_request_duration_seconds",
        lambda: HTTP_REQUEST_DURATION.labels(
            **labels,
            method=method,
            route=route,
        ).observe(max(duration_seconds, 0.0)),
    )
    _safe_record(
        "http_requests_in_progress",
        lambda: HTTP_REQUESTS_IN_PROGRESS.labels(
            **labels,
            method=method,
        ).dec(),
    )


def record_training_job_submitted(*, task_type: str, algorithm: str) -> None:
    labels = _base_labels()
    _safe_record(
        "training_jobs_submitted_total",
        lambda: TRAINING_JOBS_SUBMITTED.labels(
            **labels, task_type=task_type, algorithm=algorithm
        ).inc(),
    )


def record_training_job_finished(
    *,
    task_type: str,
    algorithm: str,
    final_status: str,
    duration_seconds: float,
) -> None:
    labels = _base_labels()
    counter = (
        TRAINING_JOBS_COMPLETED if final_status == "succeeded" else TRAINING_JOBS_FAILED
    )
    _safe_record(
        (
            "training_jobs_completed_total"
            if final_status == "succeeded"
            else "training_jobs_failed_total"
        ),
        lambda: counter.labels(
            **labels,
            task_type=task_type,
            algorithm=algorithm,
            final_status=final_status,
        ).inc(),
    )
    _safe_record(
        "training_job_duration_seconds",
        lambda: TRAINING_JOB_DURATION.labels(
            **labels,
            task_type=task_type,
            algorithm=algorithm,
            final_status=final_status,
        ).observe(max(duration_seconds, 0.0)),
    )


def record_prediction(
    *, task_type: str, algorithm: str, final_status: str, row_count: int
) -> None:
    labels = _base_labels()
    metric_labels = {
        **labels,
        "task_type": task_type,
        "algorithm": algorithm,
        "final_status": final_status,
    }
    _safe_record(
        "prediction_requests_total",
        lambda: PREDICTION_REQUESTS.labels(**metric_labels).inc(),
    )
    _safe_record(
        "prediction_rows_total",
        lambda: PREDICTION_ROWS.labels(**metric_labels).inc(max(row_count, 0)),
    )
    if final_status == "failed":
        _safe_record(
            "prediction_failures_total",
            lambda: PREDICTION_FAILURES.labels(
                **labels,
                task_type=task_type,
                algorithm=algorithm,
            ).inc(),
        )


def record_monitoring_evaluation(
    *, trigger: str, final_status: str, duration_seconds: float
) -> None:
    labels = _base_labels()
    metric_labels = {**labels, "trigger": trigger, "final_status": final_status}
    _safe_record(
        "monitoring_evaluations_total",
        lambda: MONITORING_EVALUATIONS.labels(**metric_labels).inc(),
    )
    _safe_record(
        "monitoring_evaluation_duration_seconds",
        lambda: MONITORING_EVALUATION_DURATION.labels(**metric_labels).observe(
            max(duration_seconds, 0.0)
        ),
    )


def record_monitoring_alert_created(*, alert_type: str, severity: str) -> None:
    labels = _base_labels()
    _safe_record(
        "monitoring_alerts_created_total",
        lambda: MONITORING_ALERTS_CREATED.labels(
            **labels, alert_type=alert_type, severity=severity
        ).inc(),
    )


def record_monitoring_alert_resolved(
    *, alert_type: str, severity: str, count: int = 1
) -> None:
    labels = _base_labels()
    _safe_record(
        "monitoring_alerts_resolved_total",
        lambda: MONITORING_ALERTS_RESOLVED.labels(
            **labels, alert_type=alert_type, severity=severity
        ).inc(max(count, 0)),
    )


def record_retraining_decision(
    *, trigger: str, final_status: str, request_created: bool
) -> None:
    labels = _base_labels()
    if request_created:
        _safe_record(
            "retraining_requests_total",
            lambda: RETRAINING_REQUESTS.labels(**labels, trigger=trigger).inc(),
        )
    if final_status.startswith("blocked_"):
        _safe_record(
            "retraining_requests_blocked_total",
            lambda: RETRAINING_REQUESTS_BLOCKED.labels(
                **labels, trigger=trigger, final_status=final_status
            ).inc(),
        )


def record_background_job_failure(*, job_name: str) -> None:
    labels = _base_labels()
    _safe_record(
        "background_job_failures_total",
        lambda: BACKGROUND_JOB_FAILURES.labels(
            **labels,
            job_name=job_name,
        ).inc(),
    )


def record_background_job_processed(*, job_name: str, final_status: str) -> None:
    labels = _base_labels()
    _safe_record(
        "background_jobs_processed_total",
        lambda: BACKGROUND_JOBS_PROCESSED.labels(
            **labels,
            job_name=job_name,
            final_status=final_status,
        ).inc(),
    )


def _base_labels() -> dict[str, str]:
    return {
        "service": _context.service,
        "environment": _context.environment,
    }


def _safe_record(metric_name: str, operation: Callable[[], None]) -> None:
    if not _context.enabled:
        return
    try:
        operation()
    except Exception:
        logger.warning(
            "observability_metric_collection_failed metric_name=%s",
            metric_name,
        )
