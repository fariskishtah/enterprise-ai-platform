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
_RETRIEVED_CHUNK_BUCKETS = (0, 1, 2, 3, 5, 10, 20, 50)

_DATASET_KINDS = frozenset({"tabular", "document_collection"})
_DATASET_EVENTS = frozenset(
    {
        "dataset_created",
        "version_created",
        "upload_stored",
        "processing_started",
        "processing_terminal",
        "dataset_archived",
        "version_cancelled",
        "reconciled",
    }
)
_PROCESSING_STAGES = frozenset(
    {"upload", "validation", "extraction", "chunking", "embedding", "indexing"}
)
_RAG_INDEX_EVENTS = frozenset(
    {
        "knowledge_base_created",
        "dataset_attached",
        "build_created",
        "build_started",
        "build_terminal",
        "build_cancelled",
        "reconciled",
    }
)
_FINAL_STATUSES = frozenset(
    {
        "active",
        "archived",
        "cancelled",
        "completed",
        "failed",
        "pending",
        "processing",
        "queued",
        "ready",
        "running",
        "succeeded",
    }
)
_RETRIEVAL_STATUSES = frozenset(
    {"succeeded", "insufficient_evidence", "failed", "cancelled"}
)
_CHATBOT_OUTCOMES = frozenset(
    {"grounded", "insufficient_evidence", "failed", "cancelled"}
)
_PROCESS_WORKLOADS = frozenset(
    {
        "dataset_processing",
        "document_extraction",
        "document_chunking",
        "dataset_embedding",
        "rag_indexing",
        "rag_retrieval",
        "chatbot_generation",
    }
)
_RECONCILIATION_WORKLOADS = frozenset(
    {"dataset_processing", "rag_indexing", "chatbot_generation"}
)
_RECONCILIATION_OUTCOMES = frozenset({"repaired", "unchanged", "failed"})

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
AUTOML_LIFECYCLE = Counter(
    "automl_lifecycle_total",
    "Bounded AutoML study, trial, reconciliation, and handoff outcomes.",
    ("service", "environment", "event", "final_status"),
)
AUTOML_TRIAL_DURATION = Histogram(
    "automl_trial_duration_seconds",
    "Terminal AutoML trial duration.",
    ("service", "environment", "final_status"),
    buckets=_JOB_DURATION_BUCKETS,
)
AUTOML_SLOTS_IN_USE = Gauge(
    "automl_execution_slots_in_use",
    "Durable AutoML execution slots currently held by this worker flow.",
    ("service", "environment"),
)

DATASET_LIFECYCLE = Counter(
    "dataset_lifecycle_total",
    "Bounded dataset and immutable-version lifecycle outcomes.",
    ("service", "environment", "dataset_kind", "event", "final_status"),
)
DATASET_PROCESSING_DURATION = Histogram(
    "dataset_processing_duration_seconds",
    "Dataset upload, validation, extraction, chunking, and embedding duration.",
    ("service", "environment", "dataset_kind", "stage", "final_status"),
    buckets=_JOB_DURATION_BUCKETS,
)
RAG_INDEX_LIFECYCLE = Counter(
    "rag_index_lifecycle_total",
    "Bounded knowledge-base and RAG index-build lifecycle outcomes.",
    ("service", "environment", "event", "final_status"),
)
RAG_INDEX_DURATION = Histogram(
    "rag_index_duration_seconds",
    "RAG index processing duration by fixed processing stage.",
    ("service", "environment", "stage", "final_status"),
    buckets=_JOB_DURATION_BUCKETS,
)
RAG_RETRIEVALS = Counter(
    "rag_retrieval_requests_total",
    "Authorized bounded RAG retrieval outcomes.",
    ("service", "environment", "final_status"),
)
RAG_RETRIEVAL_DURATION = Histogram(
    "rag_retrieval_duration_seconds",
    "Authorized RAG retrieval duration without query or resource labels.",
    ("service", "environment", "final_status"),
    buckets=_EVALUATION_DURATION_BUCKETS,
)
RAG_RETRIEVED_CHUNKS = Histogram(
    "rag_retrieved_chunks",
    "Number of authorized chunks returned by one bounded retrieval.",
    ("service", "environment", "final_status"),
    buckets=_RETRIEVED_CHUNK_BUCKETS,
)
CHATBOT_MESSAGES = Counter(
    "chatbot_generation_total",
    "Grounded chatbot generation outcomes without conversation or content labels.",
    ("service", "environment", "outcome"),
)
CHATBOT_GENERATION_DURATION = Histogram(
    "chatbot_generation_duration_seconds",
    "Grounded chatbot generation duration by bounded outcome.",
    ("service", "environment", "outcome"),
    buckets=_JOB_DURATION_BUCKETS,
)
PROCESS_TIMEOUTS = Counter(
    "bounded_process_timeouts_total",
    "Bounded processing operations terminated after their configured timeout.",
    ("service", "environment", "workload"),
)
RECONCILIATION_REPAIRS = Counter(
    "reconciliation_repairs_total",
    "Dataset, RAG, and chatbot reconciliation outcomes.",
    ("service", "environment", "workload", "outcome"),
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


def record_automl_event(
    *, event: str, final_status: str, duration_seconds: float | None = None
) -> None:
    labels = _base_labels()
    _safe_record(
        "automl_lifecycle_total",
        lambda: AUTOML_LIFECYCLE.labels(
            **labels, event=event, final_status=final_status
        ).inc(),
    )
    if event == "trial_terminal" and duration_seconds is not None:
        _safe_record(
            "automl_trial_duration_seconds",
            lambda: AUTOML_TRIAL_DURATION.labels(
                **labels, final_status=final_status
            ).observe(max(duration_seconds, 0.0)),
        )


def record_automl_slot_delta(delta: int) -> None:
    labels = _base_labels()
    _safe_record(
        "automl_execution_slots_in_use",
        lambda: AUTOML_SLOTS_IN_USE.labels(**labels).inc(delta),
    )


def record_dataset_lifecycle(
    *, dataset_kind: str, event: str, final_status: str
) -> None:
    """Record dataset state without accepting names, IDs, or storage metadata."""
    labels = _base_labels()
    _safe_record(
        "dataset_lifecycle_total",
        lambda: DATASET_LIFECYCLE.labels(
            **labels,
            dataset_kind=_bounded_label(dataset_kind, _DATASET_KINDS),
            event=_bounded_label(event, _DATASET_EVENTS),
            final_status=_bounded_label(final_status, _FINAL_STATUSES),
        ).inc(),
    )


def record_dataset_processing(
    *,
    dataset_kind: str,
    stage: str,
    final_status: str,
    duration_seconds: float,
) -> None:
    """Observe one bounded dataset-processing stage without content labels."""
    labels = _base_labels()
    _safe_record(
        "dataset_processing_duration_seconds",
        lambda: DATASET_PROCESSING_DURATION.labels(
            **labels,
            dataset_kind=_bounded_label(dataset_kind, _DATASET_KINDS),
            stage=_bounded_label(stage, _PROCESSING_STAGES),
            final_status=_bounded_label(final_status, _FINAL_STATUSES),
        ).observe(max(duration_seconds, 0.0)),
    )


def record_rag_index_lifecycle(*, event: str, final_status: str) -> None:
    """Record a knowledge-base/index transition using fixed vocabulary only."""
    labels = _base_labels()
    _safe_record(
        "rag_index_lifecycle_total",
        lambda: RAG_INDEX_LIFECYCLE.labels(
            **labels,
            event=_bounded_label(event, _RAG_INDEX_EVENTS),
            final_status=_bounded_label(final_status, _FINAL_STATUSES),
        ).inc(),
    )


def record_rag_index_processing(
    *, stage: str, final_status: str, duration_seconds: float
) -> None:
    """Observe a fixed RAG index stage without knowledge-base identifiers."""
    labels = _base_labels()
    _safe_record(
        "rag_index_duration_seconds",
        lambda: RAG_INDEX_DURATION.labels(
            **labels,
            stage=_bounded_label(stage, _PROCESSING_STAGES),
            final_status=_bounded_label(final_status, _FINAL_STATUSES),
        ).observe(max(duration_seconds, 0.0)),
    )


def record_rag_retrieval(
    *, final_status: str, duration_seconds: float, retrieved_chunks: int
) -> None:
    """Record authorized retrieval latency and bounded result size without text."""
    labels = _base_labels()
    safe_status = _bounded_label(final_status, _RETRIEVAL_STATUSES)
    metric_labels = {**labels, "final_status": safe_status}
    _safe_record(
        "rag_retrieval_requests_total",
        lambda: RAG_RETRIEVALS.labels(**metric_labels).inc(),
    )
    _safe_record(
        "rag_retrieval_duration_seconds",
        lambda: RAG_RETRIEVAL_DURATION.labels(**metric_labels).observe(
            max(duration_seconds, 0.0)
        ),
    )
    _safe_record(
        "rag_retrieved_chunks",
        lambda: RAG_RETRIEVED_CHUNKS.labels(**metric_labels).observe(
            max(retrieved_chunks, 0)
        ),
    )


def record_chatbot_generation(*, outcome: str, duration_seconds: float) -> None:
    """Record grounded generation without prompts, answers, or conversation IDs."""
    labels = _base_labels()
    safe_outcome = _bounded_label(outcome, _CHATBOT_OUTCOMES)
    metric_labels = {**labels, "outcome": safe_outcome}
    _safe_record(
        "chatbot_generation_total",
        lambda: CHATBOT_MESSAGES.labels(**metric_labels).inc(),
    )
    _safe_record(
        "chatbot_generation_duration_seconds",
        lambda: CHATBOT_GENERATION_DURATION.labels(**metric_labels).observe(
            max(duration_seconds, 0.0)
        ),
    )


def record_process_timeout(*, workload: str) -> None:
    """Count one timeout using a fixed workload label."""
    labels = _base_labels()
    _safe_record(
        "bounded_process_timeouts_total",
        lambda: PROCESS_TIMEOUTS.labels(
            **labels,
            workload=_bounded_label(workload, _PROCESS_WORKLOADS),
        ).inc(),
    )


def record_reconciliation_repair(
    *, workload: str, outcome: str, count: int = 1
) -> None:
    """Count bounded reconciliation outcomes without resource identifiers."""
    labels = _base_labels()
    _safe_record(
        "reconciliation_repairs_total",
        lambda: RECONCILIATION_REPAIRS.labels(
            **labels,
            workload=_bounded_label(workload, _RECONCILIATION_WORKLOADS),
            outcome=_bounded_label(outcome, _RECONCILIATION_OUTCOMES),
        ).inc(max(count, 0)),
    )


def _base_labels() -> dict[str, str]:
    return {
        "service": _context.service,
        "environment": _context.environment,
    }


def _bounded_label(value: str, vocabulary: frozenset[str]) -> str:
    """Collapse unexpected values so callers cannot create cardinality leaks."""
    return value if value in vocabulary else "unknown"


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
