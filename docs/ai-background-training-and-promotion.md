# AI Background Training and Model Promotion

This guide covers the local production-oriented path added after the AI Core MVP.
The original synchronous training and registered-prediction endpoints remain
available and unchanged.

## Runtime flow

```text
Authenticated request
  → PostgreSQL TrainingJob (queued)
  → Dramatiq message containing only the job UUID
  → Redis
  → dedicated worker (running)
  → typed TrackedTrainingService
  → MLflow run and immutable registered version
  → candidate alias
  → TrainingJob (succeeded)
  → explicit challenger promotion
  → explicit admin champion promotion
  → PostgreSQL promotion audit
```

Dramatiq was selected because it supports Python 3.12, Redis-backed worker
processes, bounded retries and backoff, typed actor arguments, and deterministic
test brokers without requiring a cloud service. The API does not use FastAPI
`BackgroundTasks`, and the platform does not implement a raw Redis polling loop.

## Start the local services

Create `.env`, apply migrations, and start the API, worker, PostgreSQL, and Redis:

```bash
cp .env.example .env
docker compose up --build -d postgres redis backend training-worker
docker compose exec backend alembic upgrade head
docker compose ps
docker compose logs --tail=100 backend training-worker
```

The worker exposes no public port. Redis publishes only on host loopback for
direct local Python use; it is not bound to a public interface. The backend and
worker share the PostgreSQL connection, Redis URL, MLflow file-store volume, and
AI artifact volume.

For direct Python execution, start a worker from `backend/` after exporting the
same settings as the API:

```bash
.venv/bin/dramatiq app.ml.jobs.tasks --processes 1 --threads 1
```

The sklearn fit is synchronous inside a worker process. A single process/thread
is the conservative local default; scale only after validating storage and CPU
capacity.

## Submit and inspect a job

Admin and engineer roles may submit and manage jobs. Operators cannot submit,
list, read, or cancel training jobs. Engineers see only jobs they requested;
admins see all jobs because the current user model has no company-membership
relationship from which a tenant scope could be derived.

```bash
curl -i -X POST \
  "${API_BASE_URL}/ai/training-jobs/random-forest/regression" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: regression-demo-001" \
  --data @examples/ai-core/regression-training-request.json
```

A new request returns `202 Accepted` with only `job_id`, `status`,
`submitted_at`, and `status_url`. It does not invent MLflow identifiers before
execution. Poll and list jobs with:

```bash
curl "${API_BASE_URL}/ai/training-jobs/<job-id>" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"

curl "${API_BASE_URL}/ai/training-jobs?status=succeeded&limit=50&offset=0" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"
```

The classification submission path is:

```text
POST /ai/training-jobs/random-forest/classification
```

## State and cancellation

The strict lifecycle is:

```text
queued → running → succeeded
               ↘ failed
queued → cancelled
```

Only a queued job can be cancelled:

```bash
curl -X POST "${API_BASE_URL}/ai/training-jobs/<job-id>/cancel" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"
```

Running sklearn fits do not support cooperative cancellation in this milestone.
Cancellation of a running, succeeded, failed, or already-cancelled job returns
`409 Conflict`; the API never claims that a running fit was stopped.

## Idempotency and enqueue failures

`Idempotency-Key` is optional, non-empty, and at most 128 characters. Its durable
scope is requesting user + algorithm + task + key. Canonical JSON of the
validated persisted specification is hashed with SHA-256. An equivalent repeat
returns the existing job with `200 OK`; the same key with a different payload
returns `409 Conflict`.

PostgreSQL commit and Redis enqueue are not one distributed transaction. The API
first commits the queued job and then enqueues its UUID. If enqueue fails, it
marks the job `failed` with `enqueue_failed`, returns `503`, and does not report a
false queued success.

If Redis accepts the UUID but PostgreSQL cannot persist the returned message ID,
the API preserves the queued job with a null `queue_message_id`, records
`queue_message_persistence_pending` when possible, and returns a sanitized `503`.
It does not enqueue a second message in the request. This aged null-identifier
state is repaired by reconciliation; duplicate broker delivery remains safe
because only one conditional queued-to-running claim can execute training.

## MVP request limits

Synchronous and background Random Forest training share the same bounded
transport and persisted-specification contract:

| Value | Inclusive maximum |
| --- | ---: |
| Training rows | 10,000 |
| Evaluation rows | 5,000 |
| Feature columns | 256 |
| Training + evaluation feature cells | 1,000,000 |
| User tags | 32 |
| Tag key | 250 characters |
| Tag value | 5,000 characters |
| Run name | 255 characters |
| Model description | 5,000 characters |

These are MVP request-safety limits, not scikit-learn or MLflow capability
limits. Requests outside them receive validation errors and are never persisted.

## Retry, repeated delivery, and recovery

The worker retries bounded transient MLflow/registry, operating-system storage,
and integration availability failures. Invalid persisted data, invalid
hyperparameters, trainer/model conflicts, and other deterministic validation
failures are terminal. `TRAINING_JOB_MAX_ATTEMPTS` defaults to three and
`TRAINING_JOB_RETRY_BASE_SECONDS` controls Dramatiq backoff.

A conditional status/version update lets only one worker claim a queued job.
Deliveries for succeeded, failed, or cancelled jobs are safe no-ops. The worker
checkpoints registered version identifiers before candidate-alias assignment; a
temporary alias failure retries that external step without creating another
registered version.

A process can crash after marking a job running. Dramatiq provides broker
redelivery, while the persistent claim prevents concurrent duplicate execution.
For a claim that remains running past `TRAINING_JOB_STALE_AFTER_SECONDS`, an
administrator can explicitly requeue it:

```bash
docker compose exec training-worker python -m app.ml.jobs.reconcile
```

The same command also recovers a queued job whose `queue_message_id` is null once
its `queued_at` is older than `TRAINING_JOB_ORPHANED_AFTER_SECONDS` (60 seconds by
default). This age gate avoids racing the initial submission write. The command
prints recovered UUIDs and conditionally persists each replacement message ID.
Repeated execution ignores repaired jobs. Recovery is bounded by each job's
maximum attempts; an exhausted stale claim becomes `failed` with
`retry_exhausted`. A failed recovery enqueue becomes a safe terminal
`requeue_failed` record rather than an indefinitely queued job.

Run the opt-in real Redis/Dramatiq smoke test against the disposable loopback
Redis database reserved by the test:

```bash
docker compose up -d redis
cd backend
RUN_AI_REDIS_INTEGRATION=1 \
AI_TEST_REDIS_URL=redis://localhost:6379/15 \
.venv/bin/pytest -q -m integration tests/test_ai_background_redis_integration.py
```

The test deliberately refuses non-loopback Redis hosts and databases other than
15 because it clears that disposable database before and after execution.

## Candidate, challenger, and champion

- `candidate` is assigned automatically only after background training has
  tracked and registered a model successfully.
- `challenger` is an explicit admin or engineer selection under comparison.
- `champion` is an explicit admin-approved primary model. Training never assigns
  it automatically.

Promote a successful candidate to challenger:

```bash
curl -X POST \
  "${API_BASE_URL}/ai/models/<model-name>/versions/<version>/promotions/challenger" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}'
```

An admin can then promote that exact challenger to champion:

```bash
curl -X POST \
  "${API_BASE_URL}/ai/models/<model-name>/versions/<version>/promotions/champion" \
  -H "Authorization: Bearer ${ADMIN_ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Regression policy uses evaluation-set RMSE (lower is better), a configurable
minimum R², and configurable minimum relative RMSE improvement. Classification
uses evaluation-set macro-F1 (higher is better), minimum accuracy, and minimum
absolute macro-F1 improvement. These are metrics from the evaluation arrays
supplied with the job; they are not independently collected test-set metrics.
Policy produces a recommendation, but no policy triggers promotion by itself.

Only an admin may override a rejection. The request must contain both explicit
`force: true` and a non-empty reason:

```json
{
  "force": true,
  "reason": "Approved incident response rollback after documented review."
}
```

The typed promotion request strips leading and trailing reason whitespace,
treats whitespace-only content as absent, and applies its 2,000-character limit
after normalization. The normalized reason is stored in the audit. The audit
preserves the original comparison and records the override.

Inspect governed aliases and immutable history:

```bash
curl "${API_BASE_URL}/ai/models/<model-name>/aliases" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"

curl "${API_BASE_URL}/ai/models/<model-name>/promotions" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"
```

Prediction already accepts aliases. Use `"version_or_alias": "champion"` with
the existing task-specific prediction endpoint. A model without a champion alias
returns `404`; exact-version behavior is unchanged.

## Audit and partial failures

Every policy-evaluated promotion creates a database audit before MLflow mutation.
Policy rejection and external failure finalize that audit with stable safe error
metadata. After MLflow assigns an alias, the adapter reads it back and verifies
the exact version. The previous alias holder is retained in history and no model
version is deleted.

MLflow alias mutation and database audit completion are not atomic. If audit
finalization fails after a verified alias update, the durable audit remains
`pending` and is reconciliation-ready; the platform does not pretend it can roll
back MLflow and PostgreSQL as one transaction.

Reconcile audits older than `PROMOTION_AUDIT_PENDING_AFTER_SECONDS` (five minutes
by default) with:

```bash
docker compose exec training-worker python -m app.ml.promotion.reconcile
```

Reconciliation only resolves the current alias; it never repeats alias
assignment. If the alias still points to the selected version, the pending audit
becomes `succeeded`. A missing alias or a definite different holder finalizes it
as `failed` with `promotion_reconciliation_conflict`. Registry unavailability
leaves the audit pending and reports only `registry_unavailable <audit-id>`.
Conditional pending-only completion makes repeated runs idempotent.

## Current limitations

- sklearn fitting is synchronous inside the dedicated worker process.
- Running jobs do not support cooperative cancellation.
- Promotion is explicit; there is no automated promotion or rollback endpoint.
- Redis, PostgreSQL, MLflow, and artifact persistence do not share a distributed
  transaction.
- A worker crash after MLflow changes but before the database checkpoint can
  leave an external partial run/version for later reconciliation.
- The local MLflow file store is for local Compose operation, not a cloud
  deployment design.
- Monitoring, prediction logging, drift detection, and automated retraining are
  not implemented.
- No cloud account is required.
