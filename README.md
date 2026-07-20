# AI Manufacturing Platform

Version 1.0.0 of the AI Manufacturing Platform is a Docker-based reference
platform for authenticated manufacturing data workflows and governed local
machine learning. It models companies, factories, machines, sensors, and sensor
readings, then connects bounded Random Forest training jobs to MLflow model
versioning, exact-version prediction, privacy-preserving monitoring, drift
analysis, and controlled candidate retraining.

## Project Overview

The repository is split into independently owned areas for the backend API, frontend web app, ML assets, infrastructure, Docker assets, datasets, documentation, tests, and automation scripts.

The backend is a FastAPI service using typed environment configuration, SQLAlchemy 2.0, Alembic, Pydantic v2, Pytest, Ruff, Black, and mypy. It includes JWT access tokens, refresh-token rotation, pwdlib password hashing, UUID primary keys, role-based access control, production CRUD APIs for companies, factories, machines, and sensors, sensor readings and upload-job APIs, CSV ETL using Polars and Pandera, Polars-based feature dataset exports to versioned Parquet files, and MLOps metadata management with MLflow, YAML configuration, and Optuna study preparation. The frontend is a Vite React TypeScript app using TailwindCSS, React Router, ESLint, and Prettier.

## AI Training and Prediction Architecture

The original synchronous path remains available. The background path is:

```text
FastAPI → TrainingJob → Redis/Dramatiq → Worker → TrackedTrainingService → candidate → reference profile → challenger → champion → Prediction Service → safe event → monitoring/drift → explicit retraining policy → TrainingJob → candidate
```

Prepared NumPy arrays enter through typed trainer inputs. Trainers only fit models and produce raw predictions; metrics engines only evaluate targets and predictions; the local artifact manager only persists and runtime-checks Joblib models; and the generic training engine sequences those supplied components into a typed local result. A higher-level service logs only successful executions to MLflow and then registers the completed artifact. Local artifact persistence and MLflow tracking remain separate responsibilities.

Failures propagate without cross-system rollback: a tracking failure leaves the local artifact available, and a later registry failure leaves both the local artifact and completed MLflow run available. Reconciliation for these partial-success states is a future concern.

Random Forest regression and integer-label classification are the only supported trainer tasks. Prediction resolves an exact model version or alias and performs runtime model-type and trainer-key checks before inference. Background completion assigns only `candidate`; challenger and champion changes require explicit authorized, policy-evaluated, audited requests. Prediction monitoring stores summaries rather than raw matrices and compares each version only with its own evaluation profile. Controlled retraining reuses trusted source specifications and creates candidates only. Prediction probabilities, automated promotion, external alert delivery, deployment, and online retraining are not implemented.

## AI Core Guides

- [Architecture](docs/architecture.md) summarizes the runtime components and
  main request, training, and telemetry flows.
- [v1.0.0 changelog](CHANGELOG.md) records the release scope without implying
  unsupported capabilities.
- [Release checklist](docs/release-checklist.md) defines the evidence required
  before tagging and after publishing.
- [Local reviewer demo](docs/demo-guide.md) creates a deterministic demo user,
  manufacturing hierarchy, readings, model, prediction, and audit record.
- [End-to-end testing](docs/end-to-end-testing.md) documents the focused primary
  workflow test and its resource limits.
- [AI Core API](docs/ai-core-api.md) documents authentication, request and
  response contracts, hyperparameters, metrics, failure behavior, and curl flows.
- [AI Core local demo](docs/ai-core-local-demo.md) covers Docker and direct Python
  startup, the complete training-to-prediction sequence, persistence inspection,
  and safe cleanup.
- [AI background training and promotion](docs/ai-background-training-and-promotion.md)
  documents the worker, job lifecycle, retries, idempotency, recovery, promotion
  policies, audit history, and champion prediction.
- [AI prediction monitoring and drift](docs/ai-prediction-monitoring-and-drift.md)
  documents privacy-safe events, operational and data-quality metrics, immutable
  reference profiles, drift calculations, reconciliation, and retention.
- [Controlled automated retraining](docs/ai-controlled-retraining.md) documents
  explicit drift policy, cooldowns, quotas, trusted source evidence, candidate
  comparison, governance safeguards, and bounded recovery.
- [Persisted monitoring orchestration](docs/ai-monitoring-orchestration.md)
  documents evaluation status, scheduled Dramatiq actors, internal alerts,
  retraining lineage, retention, and mature ground-truth outcomes.
- [Platform observability](docs/platform-observability.md) documents Prometheus
  metrics, exporters, cAdvisor, provisioned Grafana dashboards, privacy rules,
  and production hardening guidance.
- [Alerting, SLOs, and runbooks](docs/alerting-slos-and-runbooks.md) defines five
  30-day objectives, multi-window burn alerts, local Alertmanager routing,
  dashboards, validation, and operator response.
- [Structured logging and Loki](docs/structured-logging-and-loki.md) documents
  safe JSON logs, request and worker correlation, Alloy collection, Loki
  retention, LogQL, dashboards, and production hardening.
- [Distributed tracing and Tempo](docs/distributed-tracing-and-tempo.md) documents
  OpenTelemetry server/client/domain spans, W3C Dramatiq propagation, Tempo,
  trace/log/metric links, privacy, sampling, and production limitations.
- [Backups and disaster recovery](docs/backups-and-disaster-recovery.md) documents
  PostgreSQL backup and isolated restore verification, Redis recovery behavior,
  retention, scheduling, and local RPO/RTO targets.
- [Performance and load testing](docs/performance-and-load-testing.md) documents
  bounded k6 smoke, API, authentication, and opt-in training-job scenarios,
  thresholds, result interpretation, and pinned Docker commands.
- [Google Cloud production deployment](docs/google-cloud-production-deployment.md)
  documents the single-VM Compose topology, one-shot migrations, verification,
  HTTPS preparation, backups, rollback, monitoring, and billing safeguards.
- [AI Core MVP release checkpoint](docs/releases/ai-core-mvp.md) records delivered
  capabilities, quality evidence, architectural decisions, and known limitations.
- [`examples/ai-core/`](examples/ai-core/) contains Pydantic-validated JSON request
  payloads that can be submitted directly with `curl`.

## Folder Structure

```text
ai-manufacturing-platform/
  backend/
    app/
      api/
      core/
      config/
      db/
      models/
      schemas/
      services/
      repositories/
      dependencies/
      middleware/
      utils/
    alembic/
    requirements/
    tests/
  frontend/
    src/
      pages/
      routes/
      styles/
  ml/
  infrastructure/
  docker/
  datasets/
  docs/
  tests/
  scripts/
  .github/workflows/
```

## Local quick start

Create a local environment file:

```bash
cp .env.example .env
```

Build the stack, apply migrations, and verify health:

```bash
docker compose up --build -d
docker compose exec backend alembic upgrade head
curl --fail http://localhost:8000/health
```

Create or reuse the bounded local reviewer demo:

```bash
./scripts/seed-demo.sh
```

Run the focused primary workflow test:

```bash
cd backend && pytest -q tests/test_end_to_end_workflow.py
```

The backend container runs from `/app`. Docker Compose therefore overrides the
local relative AI storage defaults with explicit container paths and named
volumes:

```text
file:/app/data/mlflow       → mlflow-data
/app/data/model-artifacts  → model-artifact-data
/app/data/ai-artifacts     → ai-artifact-data
```

MLflow file-store data, Sprint 8 model-artifact metadata storage, and local AI
Joblib artifacts consequently survive backend container replacement. Direct
local Python execution continues to use the relative values in `.env.example`.

Backend health check:

```bash
curl http://localhost:8000/health
```

Swagger documentation:

```bash
open http://localhost:8000/docs
```

Frontend:

```bash
open http://localhost:5173
```

Local observability endpoints:

```text
Backend metrics  http://localhost:8000/metrics
Prometheus       http://localhost:9090
Alertmanager     http://localhost:9093
Loki             http://localhost:3100/ready
Alloy            http://localhost:12345/-/ready
Tempo            http://localhost:3200/ready
Grafana          http://localhost:3000
```

## Docker Commands

```bash
docker compose up --build
docker compose down
docker compose logs -f backend
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
```

## Production deployment

The supported release entry point is the reviewed single-VM Compose runbook:
[Google Cloud production deployment](docs/google-cloud-production-deployment.md).
It uses `docker-compose.prod.yml` plus the deploy and verification scripts; it
does not provision cloud infrastructure or provide high availability.

## Backups and restore verification

Create a timestamped PostgreSQL custom-format backup with a SHA-256 checksum,
then verify it by restoring only into a disposable PostgreSQL container:

```bash
./scripts/backup-postgres.sh
./scripts/verify-postgres-backup.sh backups/postgres/postgres-YYYYmmddTHHMMSSZ.dump
```

Backups default to `backups/postgres/` with seven-day retention. See the
[backup and disaster-recovery runbook](docs/backups-and-disaster-recovery.md)
before recovery; the verification command never targets the live database.

## Development Workflow

Bootstrap local dependencies:

```bash
./scripts/bootstrap.sh
```

Run all local checks:

```bash
./scripts/check.sh
```

## Continuous Integration

The [CI workflow](.github/workflows/ci.yml) runs for pull requests targeting
`main`, pushes to `main`, and manual dispatches. It applies read-only repository
permissions and cancels superseded runs for the same pull request or branch.

CI performs:

- Python 3.12 dependency checks, runtime dependency auditing, Ruff, Black, mypy,
  and one full backend Pytest run.
- Node 22 installation from `package-lock.json`, ESLint, Prettier, the TypeScript
  and Vite build, and `npm audit`.
- Docker Compose, YAML, Grafana JSON, Prometheus config/rules/tests,
  Alertmanager, Tempo, Alloy, and k6 script validation using pinned tool
  versions.
- cached Buildx builds for the repository-owned backend and frontend Dockerfiles;
  images are never pushed.

Reproduce the application checks locally with `./scripts/check.sh`, then run
`docker compose config -q`. The pinned observability validator commands and
Buildx commands are listed directly in `.github/workflows/ci.yml` so the same
commands can be copied locally without separate CI-only wrappers.

Install git hooks:

```bash
backend/.venv/bin/pre-commit install --config .pre-commit-config.yaml
```

## Implemented APIs

Authentication and current-user endpoints:

```text
POST /auth/register
POST /auth/login
POST /auth/refresh
POST /auth/logout
GET  /users/me
```

Sprint 3 exposes manufacturing endpoints:

```text
GET    /companies
POST   /companies
GET    /companies/{company_id}
PATCH  /companies/{company_id}
DELETE /companies/{company_id}
GET    /factories
POST   /factories
GET    /factories/{factory_id}
PATCH  /factories/{factory_id}
DELETE /factories/{factory_id}
GET    /machines
POST   /machines
GET    /machines/{machine_id}
PATCH  /machines/{machine_id}
DELETE /machines/{machine_id}
```

Sprint 4 exposes sensor endpoints:

```text
GET    /sensors
POST   /sensors
GET    /sensors/{sensor_id}
PATCH  /sensors/{sensor_id}
DELETE /sensors/{sensor_id}
GET    /machines/{machine_id}/sensors
```

Sprint 5 exposes backend sensor data endpoints:

```text
POST   /upload-jobs
GET    /upload-jobs
GET    /upload-jobs/{upload_job_id}
POST   /upload-jobs/{upload_job_id}/csv
POST   /sensor-readings
GET    /sensor-readings
GET    /sensor-readings/{reading_id}
GET    /sensors/{sensor_id}/readings
```

Sprint 7 exposes backend feature engineering export endpoints:

```text
POST   /feature-datasets
```

Sprint 8 exposes MLOps experiment management endpoints:

```text
GET    /experiments
POST   /experiments
GET    /experiments/{experiment_id}
POST   /experiments/{experiment_id}/training-runs
GET    /training-runs
GET    /training-runs/{training_run_id}
POST   /training-runs/{training_run_id}/model-artifacts
GET    /model-artifacts
GET    /model-artifacts/{model_artifact_id}
```

AI Core exposes compatible synchronous endpoints plus persistent jobs and model
governance:

```text
POST   /ai/training/random-forest/regression
POST   /ai/training/random-forest/classification
POST   /ai/predictions/random-forest/regression
POST   /ai/predictions/random-forest/classification
GET    /ai/models/{registered_model_name}/versions/{version_or_alias}
POST   /ai/training-jobs/random-forest/regression
POST   /ai/training-jobs/random-forest/classification
GET    /ai/training-jobs/{job_id}
GET    /ai/training-jobs
POST   /ai/training-jobs/{job_id}/cancel
POST   /ai/models/{name}/versions/{version}/promotions/challenger
POST   /ai/models/{name}/versions/{version}/promotions/champion
GET    /ai/models/{name}/promotions
GET    /ai/models/{name}/aliases
GET    /ai/monitoring/prediction-events
GET    /ai/monitoring/prediction-events/{event_id}
GET    /ai/monitoring/models/{name}/versions/{version-or-alias}/operations
GET    /ai/monitoring/models/{name}/versions/{version-or-alias}/data-quality
GET    /ai/monitoring/models/{name}/versions/{version-or-alias}/drift
GET    /ai/monitoring/models/{name}/versions/{version-or-alias}/reference-profile
GET    /ai/monitoring/evaluations
POST   /ai/monitoring/models/{name}/versions/{version}/evaluations
GET    /ai/monitoring/alerts
POST   /ai/monitoring/alerts/{alert-id}/acknowledge
PUT    /ai/monitoring/prediction-events/{event-id}/outcome
GET    /ai/monitoring/models/{name}/versions/{version}/performance
```

Public registration creates `operator` users. Admins have full manufacturing access, engineers can create/update/read, and operators are read-only.

## Architectural Decisions

- Monorepo layout keeps application, operations, datasets, ML, and documentation in one versioned workspace while preserving clear ownership boundaries.
- The backend uses a Clean Architecture directory layout so transport, configuration, persistence, services, repositories, and schemas do not collapse into one layer as the product grows.
- FastAPI is created through an application factory. This keeps runtime settings injectable, makes tests deterministic, and avoids hidden process-state coupling.
- Pydantic Settings is the only configuration entrypoint. Environment variables are documented in `.env.example` and injected into Docker Compose services.
- SQLAlchemy and Alembic manage the user and refresh-token schema through an explicit migration.
- The manufacturing domain follows the same route/schema/service/repository/model layering as authentication.
- Manufacturing deletes are soft deletes using `deleted_at` and list/read endpoints return active records only.
- Feature engineering is isolated behind a repository and service so future feature-store integration can reuse the transformation pipeline without coupling to HTTP routes.
- MLOps experiment management stores platform metadata in PostgreSQL while syncing experiment, run, and artifact metadata to MLflow through a registry abstraction.
- AI Core keeps generic local execution independent from MLflow; a separate application service orders local training, successful-run tracking, and fitted-model registration without cross-system rollback.
- Refresh tokens are stored as SHA-256 digests and rotated on refresh so logout and token reuse detection are enforceable server-side.
- Passwords are hashed with pwdlib using Argon2 through the recommended password hash profile.
- The frontend uses React Router immediately so route ownership is explicit even with only the Dashboard page.
- CI runs backend linting, formatting, type checking, and tests, plus frontend lint, build, formatting, and audit checks before changes can merge.

## Major limitations

- The production topology is a single Docker host with local PostgreSQL, Redis,
  MLflow, model artifacts, and telemetry volumes; it is not highly available.
- HTTPS certificate automation, managed secrets, off-host state, automatic
  failover, external paging, and production-scale capacity evidence are not
  included.
- Training supports bounded Random Forest regression and integer-label
  classification only. Prediction probabilities, RAG, computer vision, MQTT,
  Kafka, and automatic model promotion are not implemented.
- The frontend is a lightweight landing surface; complete workflows are exposed
  through the authenticated API and local Swagger documentation.
- The repository currently has no selected license or contribution guide. No
  reuse rights should be inferred until the owner chooses and adds a license.
- Package and runtime version declarations have not yet been consolidated into
  one canonical source; this release is identified as `v1.0.0` in release
  documentation.
