# Backend

FastAPI backend service for the AI Manufacturing Platform.

## Architecture

- `app/core` owns application construction.
- `app/api` owns HTTP routing.
- `app/schemas` owns Pydantic request and response contracts.
- `app/db` owns SQLAlchemy and Alembic integration.
- `app/services` owns authentication and user use cases.
- `app/repositories` owns SQLAlchemy persistence adapters.
- `app/dependencies` owns FastAPI dependency injection for sessions, services, and authorization.

The app is created through `create_app(settings)`, which makes configuration explicit and keeps tests independent from process-level environment state.

## Sprint 2 Authentication

The backend implements:

- User ORM model with UUID primary key and unique normalized email.
- Refresh-token metadata with hashed token storage, rotation, and revocation.
- JWT access and refresh tokens.
- pwdlib password hashing.
- Role-based access control for `admin`, `engineer`, and `operator`.
- Current-user dependency for protected routes.

Public registration creates `operator` users. Manufacturing routes use the RBAC dependency for role-specific access control.

## Sprint 3 Manufacturing Domain

The backend implements production CRUD APIs for:

- Companies.
- Factories.
- Machines.

Manufacturing entities use UUID primary keys, `created_at`, `updated_at`, soft delete support through `deleted_at`, and indexed parent relationships. List endpoints support pagination, searching, filtering, and sorting.

RBAC:

- `admin`: full access.
- `engineer`: create, update, and read.
- `operator`: read only.

## API

```text
GET  /health
POST /auth/register
POST /auth/login
POST /auth/refresh
POST /auth/logout
GET  /users/me
GET  /companies
POST /companies
GET  /companies/{company_id}
PATCH /companies/{company_id}
DELETE /companies/{company_id}
GET  /factories
POST /factories
GET  /factories/{factory_id}
PATCH /factories/{factory_id}
DELETE /factories/{factory_id}
GET  /machines
POST /machines
GET  /machines/{machine_id}
PATCH /machines/{machine_id}
DELETE /machines/{machine_id}
POST /ai/training/random-forest/regression
POST /ai/training/random-forest/classification
POST /ai/predictions/random-forest/regression
POST /ai/predictions/random-forest/classification
GET  /ai/models/{registered_model_name}/versions/{version_or_alias}
POST /ai/training-jobs/random-forest/regression
POST /ai/training-jobs/random-forest/classification
GET  /ai/training-jobs/{job_id}
GET  /ai/training-jobs
POST /ai/training-jobs/{job_id}/cancel
POST /ai/models/{name}/versions/{version}/promotions/challenger
POST /ai/models/{name}/versions/{version}/promotions/champion
GET  /ai/models/{name}/promotions
GET  /ai/models/{name}/aliases
GET  /ai/monitoring/prediction-events
GET  /ai/monitoring/prediction-events/{event_id}
GET  /ai/monitoring/models/{name}/versions/{version-or-alias}/operations
GET  /ai/monitoring/models/{name}/versions/{version-or-alias}/data-quality
GET  /ai/monitoring/models/{name}/versions/{version-or-alias}/drift
GET  /ai/monitoring/models/{name}/versions/{version-or-alias}/reference-profile
GET  /ai/monitoring/evaluations
POST /ai/monitoring/models/{name}/versions/{version}/evaluations
GET  /ai/monitoring/alerts
PUT  /ai/monitoring/prediction-events/{event-id}/outcome
GET  /ai/monitoring/models/{name}/versions/{version}/performance
```

Interactive documentation is available at `/docs` outside production.

See the repository-level [AI Core API](../docs/ai-core-api.md) and
[local demo guide](../docs/ai-core-local-demo.md) for authenticated examples and
the exact training, tracking, registration, and prediction flow. The
[background training and promotion guide](../docs/ai-background-training-and-promotion.md)
covers the Redis worker, persistent jobs, recovery, policies, and audit history.
The [prediction monitoring and drift guide](../docs/ai-prediction-monitoring-and-drift.md)
covers summary-only event capture, exact-version profiles, bounded reports,
reconciliation, and retention.
The [controlled automated retraining guide](../docs/ai-controlled-retraining.md)
documents explicit policy evaluation, trusted source evidence, persisted cooldowns
and quotas, background candidate creation, advisory comparison, and recovery.
The [persisted monitoring orchestration guide](../docs/ai-monitoring-orchestration.md)
covers durable evaluation status, internal alerts, scheduled actors, retraining
lineage, retention, and mature outcome performance summaries.
The [platform observability guide](../docs/platform-observability.md) covers the
unauthenticated metrics endpoint, bounded labels, worker metrics, Prometheus
scraping, exporters, cAdvisor, and provisioned Grafana dashboards.
The [alerting, SLOs, and runbooks guide](../docs/alerting-slos-and-runbooks.md)
defines API, background, training, and monitoring indicators, 30-day objectives,
burn alerts, Alertmanager routing, and operational response.
The [structured logging and Loki guide](../docs/structured-logging-and-loki.md)
covers the safe log schema, request/correlation headers, Dramatiq propagation,
Alloy collection, Loki queries, privacy controls, and troubleshooting.
The [distributed tracing and Tempo guide](../docs/distributed-tracing-and-tempo.md)
covers OpenTelemetry startup, normalized server spans, SQLAlchemy/Redis client
spans, W3C Dramatiq propagation, Grafana correlation, sampling, and privacy.

The API returns validated `X-Request-ID` and `X-Correlation-ID` headers on normal
responses and emits one completion log per non-noisy request. JSON is the
container default; set `LOG_FORMAT=text` for readable local output. Access logs
exclude `/metrics`, `/health`, `/docs`, and `/openapi.json`, and Uvicorn's access
logger is disabled while the application completion logger is enabled.
During a valid active OpenTelemetry span, the same JSON schema populates
`trace_id` from span context. It stays `null` outside a span and remains
independent from request and correlation IDs. Tracing excludes the same noisy
paths plus `/redoc` and never captures bodies, query strings, or arbitrary
headers.

## Local Development

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements/dev.txt
uvicorn app.main:app --reload
```

Run migrations:

```bash
alembic upgrade head
```

## Quality Checks

```bash
ruff check .
black --check .
mypy app
pytest
```
