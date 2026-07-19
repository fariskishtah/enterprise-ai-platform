# Controlled Automated Retraining

## Purpose

Controlled retraining turns an explicit drift assessment or human request into a
governed background training candidate. Drift is evidence that a distribution
changed; it is not proof that model accuracy declined. The workflow therefore
creates a new `candidate` version only. It never changes `challenger` or
`champion` and never invokes promotion internally.

Ordinary prediction does not evaluate retraining policy. An Admin or Engineer
must explicitly call the evaluation or manual-request API, or an administrator
must run a reconciliation command.

## Policy

Each registered model name has at most one current persisted policy. Admins may
create or replace policies; Engineers may read and evaluate them. Policies
validate:

- allowed `feature_drift`, `prediction_drift`, `data_quality`, and `manual`
  triggers;
- a conservative default minimum aggregate drift level of `critical`, with an
  explicit `warning` option;
- a minimum analyzed sample count;
- whether a truncated newest-event window is allowed (the truncation warning is
  always retained in the decision);
- an exact-model cooldown beginning when an automatic request is accepted;
- persisted daily, weekly, and active-request quotas; and
- whether the source version must be the exact current `champion`.

The default limits are one automatic request per model per day, three per week,
one active request, and a 24-hour cooldown. A deterministic SHA-256 key scopes
duplicate protection to the model name, exact source version, trigger type,
monitoring-window identity, and policy update. The database uniqueness constraint
is authoritative across retries and API replicas.
An equivalent terminal failure remains deduplicated for the same trigger and
policy version; a later monitoring window or explicit policy update creates a new
effective scope that may be evaluated again.

Evaluation order is stable: enabled policy, allowed trigger, exact source,
champion requirement, reference profile, sample sufficiency, threshold, training
evidence, equivalent duplicate, active limit, cooldown, daily quota, weekly quota,
then eligibility. Blocked evaluation is a successful audited decision and creates
no training job.

## Training evidence and lineage

Retraining uses the successful background `TrainingJob` associated with the exact
source model version. Its persisted, validated specification provides the trusted
features, targets, evaluation data, trainer key, dimensions, and model name.
Monitoring summaries and prediction events are never treated as training data.

The copied specification is immutable and receives protected lineage tags:
`retraining`, `retraining_request_id`, `retraining_trigger`,
`source_model_version`, `source_training_job_id`, and `retraining_policy_id`.
User tags cannot replace those values. Submission then uses the existing
`TrainingJobService`, Redis/Dramatiq actor, tracked training flow, MLflow
registration, and candidate assignment.

This is safe automated rerun orchestration, not online learning. The platform
does not yet ingest verified production labels or synthesize training rows from
monitoring data.

## API and roles

All endpoints require a bearer access token:

```text
GET  /ai/retraining/policies
GET  /ai/retraining/policies/{registered_model_name}
PUT  /ai/retraining/policies/{registered_model_name}
GET  /ai/retraining/status
POST /ai/retraining/models/{name}/versions/{version-or-alias}/evaluate
POST /ai/retraining/models/{name}/versions/{version-or-alias}/requests
GET  /ai/retraining/requests
GET  /ai/retraining/requests/{request_id}
GET  /ai/retraining/requests/{request_id}/comparison
GET  /ai/retraining/audits
```

- Admins manage policies, evaluate drift, request manual retraining, view audits,
  and may explicitly override cooldown with a required audited reason.
- Engineers read policies and requests, evaluate drift, and request retraining
  without cooldown override.
- Operators cannot submit retraining, alter policy, or view detailed retraining
  evidence.

Evaluation responses include the exact source version, requested alias, bounded
drift summary, thresholds, decision reasons, cooldown state, quota state,
duplicate request identity, and any created request/job/candidate lineage. They do
not expose training matrices, idempotency keys, local artifact paths, or raw
prediction events. Errors remain sanitized; normal policy blocks return a 200
decision such as `blocked_cooldown`.

Manual requests still require trusted source evidence and respect active limits
and cooldown. Only Admin may set `override_cooldown=true`, and the supplied reason
is retained with the override audit. Manual requests do not consume the automatic
daily and weekly quotas.

## Candidate comparison and governance

After the existing worker registers the candidate, retraining compares its stored
evaluation metrics with the exact source job. Regression treats lower RMSE/MAE and
higher R² as better. Classification treats higher macro-F1 and accuracy as better.
The result is `better`, `worse`, `mixed`, or `not_comparable` and is advisory only.

The worker's existing candidate assignment is the only alias action in this
workflow. Champion never changes automatically. Challenger/champion transitions
remain separate explicit calls governed by the existing promotion policy and
append-only promotion audit.

## Recovery and reconciliation

Requests checkpoint before job submission and link the existing job afterward.
The worker performs a noncritical targeted request synchronization after its
authoritative job transition. If that update or submission linking is interrupted,
run:

```bash
cd backend
.venv/bin/python -m app.ml.retraining.reconcile
```

One bounded pass resumes a persisted request with no job, synchronizes running or
terminal job state, records the resulting version, and fills a missing candidate
comparison. It never retrains when a job is already linked, never registers a
model, and never promotes an alias. Repeated passes are idempotent and print only
safe counts.

Cancellation is intentionally omitted from the retraining API in this milestone.
The existing training-job cancellation endpoint remains the only safe queued-job
cancellation boundary; completed candidate versions are not deleted or rolled
back.

## Persisted monitoring evaluation integration

The monitoring orchestrator can pass one immutable evaluation to this same
policy. Requests and audits retain its ID, and the evaluation-derived trigger is
idempotent. All champion-source, trusted specification, cooldown, quota,
truncation, active-request, and duplicate checks remain authoritative. Automatic
submission is separately disabled by default and never promotes the resulting
candidate. See
[Persisted AI Monitoring Orchestration](ai-monitoring-orchestration.md).

## Limitations

- no embedded clock-based scheduler;
- no automated promotion, rollback, or alert delivery;
- no retraining trigger based on ground-truth performance yet;
- no online learning, streaming retraining, or new-dataset collection;
- no feature-engineering or hyperparameter-tuning orchestration;
- no tenant scoping; and
- no automatic deletion of registered candidate versions.
