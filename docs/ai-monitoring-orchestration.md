# Persisted AI Monitoring Orchestration

This guide covers exact-version monitoring evaluations, internal alerts,
Dramatiq maintenance actors, controlled-retraining integration, and the safe
ground-truth foundation. Existing prediction-event, live operational,
data-quality, drift, and reference-profile API contracts remain unchanged.

## Evaluation lifecycle and status

One `ModelMonitoringEvaluation` identifies an immutable registered model version
and a half-open UTC window. The service resolves an alias once, records the exact
version and alias observed at that time, verifies the reference profile, invokes
the existing bounded operations/data-quality/drift services, derives component
statuses, stores a schema-versioned JSON report, updates internal alerts, and
commits them together.

No raw feature rows, raw prediction arrays, training matrices, prompts,
credentials, artifact paths, or unfiltered exception messages enter the report.
It contains only aggregate values already produced by monitoring.

Overall status precedence is deterministic:

1. `unavailable` when a required input cannot be trusted or loaded;
2. `critical` when any available component is critical;
3. `warning` when no component is critical but at least one warns;
4. `insufficient_data` when no higher state applies and the sample minimum is
   not met; and
5. `healthy` when every component is healthy.

The operational component uses configured warning and critical prediction
failure-rate thresholds. Missing reference profiles become safe `unavailable`
evaluations so that the condition is auditable and alertable.

Database uniqueness covers both the idempotency key and exact model
name/version/window. Concurrent or retried requests converge on one logical
evaluation. Scheduled keys derive from model name, exact version, window start,
and window end.

## APIs and roles

```text
GET  /ai/monitoring/evaluations
GET  /ai/monitoring/evaluations/{evaluation_id}
GET  /ai/monitoring/models/{name}/versions/{version}/evaluations
POST /ai/monitoring/models/{name}/versions/{version}/evaluations
GET  /ai/monitoring/models/{name}/versions/{version}/status/latest
GET  /ai/monitoring/alerts
GET  /ai/monitoring/alerts/{alert_id}
POST /ai/monitoring/alerts/{alert_id}/acknowledge
POST /ai/monitoring/alerts/{alert_id}/resolve
PUT  /ai/monitoring/prediction-events/{event_id}/outcome
GET  /ai/monitoring/models/{name}/versions/{version}/performance
```

Admins and engineers may manually evaluate exact numeric versions and submit
outcomes. Operators may read evaluation history, latest aggregate status, and
performance summaries. Alert detail and acknowledgement require Admin or
Engineer; manual resolution requires Admin. Every list has a maximum page size
of 100 and a bounded offset. Time filters must be a complete bounded pair. The
repository has no company-membership-to-model mapping, so current platform RBAC
is the available isolation boundary.

## Alert lifecycle

Internal alerts cover critical feature drift, critical prediction drift, high
failure rate, a missing reference profile, insufficient or absent recent
predictions, evaluation unavailability, and the process-local prediction-event
persistence-failure signal.

The deduplication key is the alert type plus exact model identity. A repeated
condition increments `occurrence_count`, updates `last_detected_at`, and reopens
a resolved alert. Acknowledgement records the authenticated actor. A later
evaluation resolves conditions it clears. Alerts use fixed safe summaries rather
than exception strings. No Slack, email, Teams, PagerDuty, or webhook delivery is
implemented.

## Scheduled jobs

The existing worker imports Dramatiq actors for monitoring evaluation,
prediction-event retention, monitoring-evaluation retention, reference-profile
reconciliation, controlled-retraining reconciliation, and stale-alert
reconciliation. Every actor is disabled by default.

The repository does not embed a clock scheduler. A trusted production scheduler
should enqueue the named actor at the configured interval. The evaluation actor
floors its window end to `MONITORING_EVALUATION_INTERVAL_SECONDS`, acquires an
expiring database lock, and evaluates all configured aliases. One model failure
does not stop other models. Repeated delivery is safe, and no actor changes
`champion` or `challenger`.

Example local enqueue after the worker is running:

```bash
cd backend
.venv/bin/python -c \
  'from app.ml.jobs.tasks import execute_scheduled_monitoring; execute_scheduled_monitoring.send()'
```

Production scheduling should use one external enqueue per interval, retry later
than the database lock timeout, and alert on the actor's safe failed count.

## Controlled retraining

A completed evaluation can enter the existing `RetrainingService` policy.
`eligible` is the recommendation/accepted state; existing `not_eligible` and
`blocked_*` values are safe policy outcomes. Requests and append-only audits
store the evaluation ID.

Automatic submission requires all of these:

- `MONITORING_AUTOMATIC_RETRAINING_ENABLED=true`;
- a valid `MONITORING_RETRAINING_ACTOR_USER_ID`;
- a persisted enabled model policy; and
- every existing champion, trusted evidence, sample, truncation, cooldown,
  quota, active-request, and duplicate check to pass.

Critical drift alone cannot bypass governance. Training reuses the trusted
stored specification and assigns only `candidate`. Champion promotion remains a
separate authorized, audited operation. The evaluation foreign key and existing
retraining idempotency key prevent duplicate requests.

## Retention and reconciliation

Prediction-event and monitoring-evaluation retention are dry-run by default:

```bash
cd backend
.venv/bin/python -m app.ml.monitoring.retention --dry-run
.venv/bin/python -m app.ml.monitoring.retention --execute
.venv/bin/python -m app.ml.monitoring.maintenance evaluation-retention
.venv/bin/python -m app.ml.monitoring.maintenance evaluation-retention --execute
.venv/bin/python -m app.ml.monitoring.maintenance stale-alerts
```

Each execution deletes or repairs at most its configured batch. Evaluation
retention excludes evaluations referenced by any retraining request or audit;
governance evidence is never deleted. Reconciliation is idempotent and does not
fit another model, register another version, or mutate production aliases.

## Ground-truth outcomes and performance

An authenticated Admin or Engineer may upsert one observed target for a
successful, single-row prediction event. The record contains a typed actual
value, observation time, source, label-maturity time, bounded string metadata,
and an optional unique external reference. Classification requires an integer
label; regression requires a finite number. One row per prediction event and a
unique external key prevent duplicates.

Performance joins only mature outcomes. For single-row events, existing safe
summaries retain enough information to recover the one prediction. Regression
reports MAE, RMSE, mean prediction bias, and sample count. Binary classification
reports accuracy, precision, recall, F1, false-negative rate, and TP/TN/FP/FN.

Privacy-driven limitations are explicit: batch events cannot be scored because
per-row predictions are not stored, and confusion-matrix metrics currently
support binary labels `0` and `1`. Summary-only storage is not weakened to fill
those gaps.

## Configuration

The complete defaults are in `.env.example`:

```text
MONITORING_SCHEDULING_ENABLED=false
MONITORING_QUEUE_NAME=ai-monitoring
MONITORING_WINDOW_HOURS=24
MONITORING_EVALUATION_INTERVAL_SECONDS=3600
MONITORING_LOCK_TIMEOUT_SECONDS=1800
MONITORING_ELIGIBLE_MODEL_ALIASES=champion
MONITORING_MAX_MODELS_PER_RUN=100
MONITORING_FAILURE_RATE_WARNING_THRESHOLD=0.05
MONITORING_FAILURE_RATE_CRITICAL_THRESHOLD=0.20
MONITORING_EVALUATION_RETENTION_DAYS=365
MONITORING_EVALUATION_RETENTION_BATCH_SIZE=500
MONITORING_STALE_ALERT_HOURS=168
PREDICTION_EVENT_RETENTION_SCHEDULING_ENABLED=false
MONITORING_EVALUATION_RETENTION_SCHEDULING_ENABLED=false
REFERENCE_PROFILE_RECONCILIATION_SCHEDULING_ENABLED=false
RETRAINING_RECONCILIATION_SCHEDULING_ENABLED=false
STALE_ALERT_RECONCILIATION_SCHEDULING_ENABLED=false
MONITORING_AUTOMATIC_RETRAINING_ENABLED=false
MONITORING_RETRAINING_ACTOR_USER_ID=
GROUND_TRUTH_MAX_OUTCOMES_PER_SUMMARY=10000
```

## Local verification and limitations

```bash
cd backend
.venv/bin/ruff check .
.venv/bin/black --check .
.venv/bin/mypy app
.venv/bin/pytest
.venv/bin/alembic upgrade head
```

There is no external alert delivery, embedded periodic clock, classification
probability drift, multi-row performance join, multiclass confusion matrix,
model-to-company tenant mapping, online learning, automatic promotion, or
automatic rollback. The event persistence-failure counter remains process-local.
