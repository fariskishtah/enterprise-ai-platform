# AI Prediction Monitoring and Drift

This guide describes the local-first prediction-event, operational monitoring,
reference-profile, data-quality, and drift boundaries. Drift reports are evidence,
not proof of reduced accuracy. An authorized caller may evaluate them through the
separate [controlled retraining workflow](ai-controlled-retraining.md); monitoring
never submits training as a prediction side effect. This guide does not add
automated alerts, promotion, or model rollback.

## Event capture and privacy

Each valid authenticated prediction attempt can produce one `prediction_events`
row after prediction completes. Authentication failures and FastAPI/Pydantic
transport failures occur before the capture boundary and are not events. Model
resolution, trainer-key validation, artifact loading, prepared-feature validation,
and prediction failures are captured when the database is available.

An event stores the requesting user internally for governance, model name,
requested version or alias, exact resolved version and aliases when resolution
succeeded, `TrainerKey`, timestamps, duration, row/column counts, terminal status,
optional correlation ID, and stable safe failure fields. Event API responses omit
the requester ID.

Complete feature matrices and complete prediction vectors are never persisted.
Each feature column is reduced to counts, missing/finite counts, minimum, maximum,
mean, population standard deviation, selected quantiles, optional fixed-bin
counts, and an out-of-reference-range count. Regression predictions use the same
numeric summary. Classification predictions use a frequency map capped at 100
labels plus `other_count`. Tokens, arbitrary headers, exception traces, model
objects, Joblib payloads, and MLflow SDK responses are not stored.

The API response and database write cannot be atomic. Prediction runs exactly
once. A successful result remains successful if reference lookup or event
persistence fails; the application logs a safe exception, rolls the monitoring
transaction back, and increments a process-local
`instance_capture_failures_since_start` diagnostic. It does not rerun or enqueue
prediction. A monitoring write failure also never replaces the original
prediction exception. The diagnostic belongs only to the API process serving the
operational-summary request, resets when that process restarts, is not filtered by
the requested monitoring window, is not aggregated across replicas, and is not a
durable historical metric. It is never added to database-backed event failures.

Persisted `duration_ms` stops immediately after the existing prediction execution
path: model resolution, `TrainerKey` validation, trusted artifact loading, feature
validation, and model prediction. Feature and prediction summarization, reference
profile lookup, event repository work, commit/rollback, and monitoring logging run
after that timer stops and cannot alter the recorded prediction latency.

## Reference profiles

Successful background training already holds bounded evaluation matrices in its
persisted job specification. The external training result, including the MLflow
run and exact registered model version, is checkpointed before `candidate`
assignment. After that safe alias assignment, the worker attempts to persist an
immutable `model_reference_profiles` row before marking the job successful. The
row is uniquely owned by registered model name plus exact version and links to
its training job. A champion profile is never reused for another version.

Profiles contain the protected trainer key, evaluation source, sample and feature
counts, one numeric reference per feature, and a task-specific prediction
reference. Numeric references retain summary statistics and deterministic
quantile boundaries. The configured `MONITORING_PROFILE_BIN_COUNT` is between 10
and 20. Internal persisted edges define bins with implicit underflow and overflow
ends; duplicate quantiles are removed, so constant features remain valid. Current
windows always use these stored edges and never recalculate them.

Reference construction or persistence is noncritical to model usability. The
registered version remains prediction-ready, the job is marked successful, and
the version is neither retrained nor registered again. A missing profile is a
visible recoverable monitoring degradation and profile-dependent endpoints return
404. Duplicate worker delivery skips the terminal job rather than repeating
candidate assignment. Run a bounded, idempotent reconciliation batch with:

```bash
cd backend
.venv/bin/python -m app.ml.monitoring.reconcile
```

Reconciliation finds successful jobs without profiles, loads the existing exact
registered version, predicts the already-persisted bounded evaluation features,
and creates only the profile. It never fits, registers, or promotes a model.
Repeated reconciliation finds no further work after the unique profile is
created. Registry or loader failures are logged with job identity and safe command
counts, leave the same successful job and registered version untouched, and can be
retried later; the configured batch bound prevents an infinite loop.

## Operational and data-quality monitoring

Operational reports resolve an alias once and report its exact version. The
default window is the previous 24 hours; explicit `start_at` and `end_at` values
must be timezone-aware, ordered, and no longer than
`MONITORING_MAX_WINDOW_DAYS`. Reports include request/success/failure counts and
rates, average/minimum/maximum latency, linearly interpolated p50/p95/p99 latency,
total predicted rows, average batch size, and failures grouped only by stable
error code. Percentiles read at most `MONITORING_MAX_EVENTS_PER_WINDOW` ordered
durations. Selection is deterministic: the newest matching events are selected by
descending creation time with event ID as the tie-breaker, then their durations
are sorted for cross-SQLite/PostgreSQL percentile calculation. Responses expose
`matched_event_count`, `analyzed_event_count`, `truncated`, and an explicit warning
when the percentile input is partial. Other operational totals remain
database-backed across the complete matching window.

Data-quality reports count missing and non-finite values, feature-count mismatch
requests, empty batches, constant columns within requests, and values outside the
version reference range. Current HTTP prediction validation rejects empty,
ragged, non-finite, over-limit, or zero-column matrices before this application
capture boundary. Therefore a valid but out-of-range value is a warning about
distribution, not an assertion that the request is invalid.

Data-quality and drift calculations use the same deterministic newest-event
selection and never load more than `MONITORING_MAX_EVENTS_PER_WINDOW`. Their
responses expose matched and analyzed event counts, truncation, and a partial-
window warning. At exactly the limit the complete matched set is analyzed; one
event over the limit selects only the newest configured number. Drift sample
sufficiency is calculated only from rows in those analyzed events, never from the
larger matched count. A `stable` result with `truncated=true` is therefore
explicitly qualified as partial-window analysis rather than a claim about the
complete window.

## Drift calculation

The drift engine is pure application logic: it imports no FastAPI, SQLAlchemy,
MLflow, Dramatiq, or Joblib code. It consumes one immutable exact-version profile
and bounded event summaries.

- Numeric feature drift uses Population Stability Index (PSI) over fixed
  reference bins. Zero proportions use epsilon smoothing (`1e-6`) to avoid
  division by zero. Missing-rate difference and out-of-reference-range proportion
  accompany PSI.
- Regression prediction drift uses PSI plus mean shift and standard-deviation
  ratio when the reference deviation is nonzero.
- Classification prediction drift uses total variation distance across predicted
  label frequencies. It is label-distribution drift, not probability drift.

The configurable operational defaults are PSI/total-variation warning at `0.10`
and critical at `0.25`. These are platform defaults, not universal scientific
truth. Threshold boundaries are inclusive: warning begins at the warning value
and critical begins at the critical value. Any critical required result makes the
aggregate critical; otherwise warning wins, then `insufficient_data`, then
stable. A window below `MONITORING_MIN_SAMPLE_COUNT`, or one lacking compatible
fixed-bin counts, reports `insufficient_data` rather than estimating drift.

Drift indicates a distribution change. It does not prove accuracy or model
quality degradation. The outcome foundation can score only mature, single-row
events that retain an exact summary prediction; see
[Persisted AI Monitoring Orchestration](ai-monitoring-orchestration.md).

## APIs and RBAC

All endpoints require a bearer access token:

```text
GET /ai/monitoring/prediction-events
GET /ai/monitoring/prediction-events/{event_id}
GET /ai/monitoring/models/{name}/versions/{version-or-alias}/operations
GET /ai/monitoring/models/{name}/versions/{version-or-alias}/data-quality
GET /ai/monitoring/models/{name}/versions/{version-or-alias}/drift
GET /ai/monitoring/models/{name}/versions/{version-or-alias}/reference-profile
```

Admins and engineers may list/read event summaries. Operators cannot access event
history, but may read aggregate operations, quality, profile, and drift responses
for models they can already use. No monitoring response contains requester IDs.
The repository currently has no tenant abstraction; model-level aggregates are
platform-wide within this role boundary.

Example exact-version operational query:

```bash
curl \
  "${API_BASE_URL}/ai/monitoring/models/ai_core_random_forest_regression/versions/1/operations" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"
```

Example alias drift query with an explicit UTC window and sample minimum:

```bash
curl \
  "${API_BASE_URL}/ai/monitoring/models/ai_core_random_forest_regression/versions/champion/drift?start_at=2026-07-17T00:00:00Z&end_at=2026-07-18T00:00:00Z&minimum_sample_count=20" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"
```

Errors use 401/403 for authentication/authorization, 404 for missing versions,
events, or profiles, 409 for profile/report preconditions, 422 for invalid model
references or windows, 502 for sanitized registry failures, and 503 for
sanitized monitoring-database failures.

## Retention

`PREDICTION_EVENT_RETENTION_DAYS` defaults to 90. Cleanup never runs inside an
API request. Its Dramatiq actor is disabled by default, while the command defaults
to dry-run:

```bash
cd backend
.venv/bin/python -m app.ml.monitoring.retention --dry-run
```

Explicitly delete one oldest bounded batch with:

```bash
.venv/bin/python -m app.ml.monitoring.retention --execute
```

`--execute` is destructive for eligible prediction events. Repeated runs are
idempotent and each run deletes at most
`PREDICTION_EVENT_RETENTION_BATCH_SIZE`. It never deletes reference profiles,
training jobs, promotion audits, registered models, or artifacts. Production
scheduling requires an external scheduler to enqueue the explicitly enabled
actor.

## Configuration

```text
PREDICTION_EVENT_RETENTION_DAYS=90
PREDICTION_EVENT_RETENTION_BATCH_SIZE=1000
MONITORING_MIN_SAMPLE_COUNT=20
MONITORING_MAX_WINDOW_DAYS=30
MONITORING_PROFILE_BIN_COUNT=10
MONITORING_MAX_EVENTS_PER_WINDOW=10000
MONITORING_REFERENCE_RECONCILIATION_BATCH_SIZE=100
DRIFT_PSI_WARNING_THRESHOLD=0.10
DRIFT_PSI_CRITICAL_THRESHOLD=0.25
DRIFT_MISSING_RATE_WARNING_THRESHOLD=0.05
DRIFT_OUT_OF_RANGE_WARNING_THRESHOLD=0.10
```

Counts are positive and bounded, bin counts remain between 10 and 20, numeric
thresholds are finite, and the warning threshold must be lower than critical.
No cloud resource is required.

## Current limitations

- No external alert delivery or real-time event streaming.
- No classification probability drift.
- Performance requires mature outcomes for single-row events.
- No automated promotion, rollback, or remediation.
- Scheduling requires an external clock to enqueue the provided Dramatiq actors.
- No cloud object storage or multi-tenant monitoring scope.
- The event-write failure counter is process-local.
- Drift indicates distribution change, not guaranteed model-quality degradation.
