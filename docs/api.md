# API surface

This guide summarizes the implemented HTTP domains in controlled-pilot version
`0.9.0`. The running FastAPI OpenAPI document is the field-level contract:

```bash
curl http://127.0.0.1:8000/openapi.json
open http://127.0.0.1:8000/docs
```

API documentation is disabled in production. Routes remain available through
the production `/api/` proxy prefix.

## Common behavior

- Protected routes require `Authorization: Bearer <access-token>`.
- Roles are enforced by backend dependencies, not frontend visibility.
- List APIs use bounded `limit`/`offset` pagination where defined.
- Sensitive mutations use distributed rate limiting.
- Supported idempotent submissions accept `Idempotency-Key`.
- Responses propagate validated `X-Request-ID` and `X-Correlation-ID`.
- Validation uses `422`, authorization `401`/`403`, conflicts `409`, and
  unavailable dependencies sanitized `503` responses.
- Sensitive API responses are marked `Cache-Control: no-store`.

## Health and operations

```text
GET /health
GET /ready
GET /operational-status
GET /metrics
```

`/health` is process liveness. `/ready` checks PostgreSQL. Operational status
reports sanitized database, Redis, queue, worker-heartbeat, dataset-storage,
embedding, generation, RAG-index, and reconciliation state. Public Nginx blocks
`/api/metrics`.

## Authentication and current user

```text
POST /auth/register
POST /auth/login
POST /auth/refresh
POST /auth/logout
GET  /users/me
```

Public registration creates an operator. User invitations, role administration,
password reset, MFA, and account mutation are not implemented.

## Manufacturing hierarchy

```text
GET|POST              /companies
GET|PATCH|DELETE      /companies/{company_id}
GET|POST              /factories
GET|PATCH|DELETE      /factories/{factory_id}
GET|POST              /machines
GET|PATCH|DELETE      /machines/{machine_id}
GET|POST              /sensors
GET|PATCH|DELETE      /sensors/{sensor_id}
GET                   /machines/{machine_id}/sensors
```

Admins may delete. Admins and engineers may create/update. Operators are
read-only.

## Sensor data and feature export

```text
POST /upload-jobs
GET  /upload-jobs
GET  /upload-jobs/{upload_job_id}
POST /upload-jobs/{upload_job_id}/csv
POST /sensor-readings
GET  /sensor-readings
GET  /sensor-readings/{reading_id}
GET  /sensors/{sensor_id}/readings
POST /feature-datasets
```

CSV upload validates and imports immediately. Results expose aggregate row
counts; row-level rejection reasons are not available.

## MLOps metadata

```text
GET|POST /experiments
GET      /experiments/{experiment_id}
POST     /experiments/{experiment_id}/training-runs
GET      /training-runs
GET      /training-runs/{training_run_id}
POST     /training-runs/{training_run_id}/model-artifacts
GET      /model-artifacts
GET      /model-artifacts/{model_artifact_id}
```

## Training, registry, prediction, and governance

The `/ai` domain includes synchronous Random Forest compatibility training;
allowlisted background plugin and Random Forest jobs; job list/detail/
cancellation/evaluation; registered-version lookup and discovery; exact-version
or alias prediction; candidate/challenger/champion governance; and promotion
audits. Background submissions enqueue only a persisted job identifier.

Use the generated OpenAPI operation list and [AI Core API](ai-core-api.md) for
exact request/response schemas.

## AutoML

```text
GET  /ai/automl/algorithms
POST /ai/automl/studies
GET  /ai/automl/studies
GET  /ai/automl/studies/{study_id}
GET  /ai/automl/studies/{study_id}/trials
GET  /ai/automl/studies/{study_id}/trials/{trial_id}
POST /ai/automl/studies/{study_id}/cancel
GET  /ai/automl/studies/{study_id}/leaderboard
```

Admins see all studies; engineers are owner-scoped. Search spaces, budgets,
trial counts, folds, execution time, and execution slots are bounded.

## Prediction monitoring and retraining

`/ai/monitoring` provides prediction-event history/detail, operational and
request-data-quality summaries, reference profiles, drift reports, persisted
evaluations, internal alerts, prediction outcomes, performance summaries, and
authorized maintenance operations. Events omit raw feature matrices.

`/ai/retraining` provides policies, drift evaluation, explicit manual requests,
request lifecycle, reconciliation, candidate comparison, and append-only
decision audits. Only admins manage policy and cooldown overrides. No retraining
path automatically promotes a candidate.

See [monitoring and drift](ai-prediction-monitoring-and-drift.md),
[monitoring orchestration](ai-monitoring-orchestration.md), and
[controlled retraining](ai-controlled-retraining.md).

## Dataset registry

```text
GET|POST /ai/datasets
GET      /ai/datasets/{dataset_id}
POST     /ai/datasets/{dataset_id}/archive
GET|POST /ai/datasets/{dataset_id}/versions
GET      /ai/datasets/{dataset_id}/versions/{version_id}
GET      /ai/datasets/{dataset_id}/versions/{version_id}/documents
GET      /ai/datasets/{dataset_id}/versions/{version_id}/documents/{document_id}
POST     /ai/datasets/{dataset_id}/versions/{version_id}/cancel
```

Dataset versions are immutable. Admins can inspect all owners; engineers are
owner-scoped. Operators cannot use this domain.

## Knowledge bases, retrieval, and chat

`/ai/rag` provides owner-scoped knowledge-base list/create/detail/archive,
attach/detach of ready document dataset versions, asynchronous index
build/cancel/history, and bounded authorized search.

`/ai/chat` provides owner-scoped conversation list/create/detail/archive,
message history, asynchronous idempotent submission, message detail, and
cancellation. Successful assistant messages return a grounded or
insufficient-evidence outcome and persisted citations.

See [Data Registry, RAG, and Chatbot Operations](data-rag-operations.md).

## Deliberately unsupported API areas

- User/role administration beyond `/users/me`.
- Password recovery/change, MFA, SSO/SAML/OIDC, SCIM, and session inventory.
- Tenant provisioning, billing, entitlements, or customer administration.
- Complete cross-domain audit-event query/export.
- PDF/DOCX/OCR/connectors or arbitrary RAG URLs.
- Automatic model promotion, arbitrary code execution, or online retraining.
