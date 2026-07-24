# AI Manufacturing Platform

Version **0.9.0** is a controlled-pilot release of an authenticated
manufacturing data, MLOps, monitoring, and grounded-knowledge platform. The
implementation connects industrial hierarchy and sensor workflows to immutable
datasets, governed model training, prediction monitoring, controlled retraining,
and citation-aware answers over registered documents.

The exact supported and deferred capabilities are defined in the
[controlled-pilot scope](docs/release/supported-scope.md). This repository is not
yet licensed for commercial redistribution; see the
[legal readiness checklist](docs/release/legal-readiness-checklist.md).

## Architecture

```text
Browser
  → Nginx reverse proxy
    → React/TypeScript frontend
    → FastAPI backend
      → PostgreSQL + pgvector
      → Redis queues, rate limits, and worker heartbeat
      → Dramatiq worker
        → MLflow registry and local model/artifact volumes
        → immutable dataset object volume
      → Prometheus, Loki, Tempo, Grafana, and Alertmanager
```

PostgreSQL is authoritative for users, manufacturing resources, workflow state,
datasets, model governance, monitoring, retraining, RAG indexes, conversations,
and citations. Redis provides bounded distributed coordination. Worker messages
contain stable resource identifiers; workers reload authoritative state and use
conditional transitions so repeated delivery is safe.

See [architecture](docs/architecture.md) for the detailed monorepo, clean
architecture, data-flow, deployment, and observability diagrams.

## Implemented product areas

- JWT login, refresh rotation, logout, admin/engineer/operator RBAC, and
  company-scoped user, password, and session lifecycle controls.
- Company → factory → machine → sensor hierarchy.
- Manual sensor readings and bounded CSV upload jobs.
- Owner-scoped dataset registry with immutable tabular/document versions.
- Synchronous compatibility training plus persisted background training jobs.
- Allowlisted sklearn model plugins, bounded AutoML, MLflow versions, and
  explicit candidate/challenger/champion governance.
- Exact-version prediction, summary-only prediction events, monitoring,
  data-quality reports, drift, evaluations, alerts, outcomes, and controlled
  candidate retraining.
- Owner-scoped knowledge bases, asynchronous indexing, pgvector cosine ranking,
  grounded/insufficient-evidence outcomes, and citations.
- React routes for manufacturing, datasets, training, AutoML, models,
  predictions, monitoring, retraining, knowledge bases, and chat.
- Company-scoped, append-only audit history with bounded filters and CSV/JSON
  export for critical identity, data, model, prediction, alert, and retraining
  actions.
- Docker Compose local/staging/single-host deployment, optional HTTPS, backup,
  isolated restore verification, rollback, smoke, and observability tooling.

Enterprise identity federation and automated tenant provisioning, HA, off-host
durable storage, semantic/LLM RAG, advanced document ingestion, billing, and
entitlements are explicitly outside this release.

## Repository layout

```text
backend/
  app/                 API, configuration, services, repositories, domain code
  alembic/versions/    ordered database migrations
  requirements/        hashed production and development locks
  tests/               unit, integration, resilience, worker, and release tests
frontend/
  src/                 React application, typed API clients, routes, shared UI
  e2e/                 fixture and real-backend Playwright suites
docker/                backend and frontend image definitions
infrastructure/        Nginx and the observability stack
performance/           bounded k6 smoke/load scenarios
scripts/               setup, validation, demo, staging, deployment, backup
docs/                  product, architecture, security, release, and runbooks
VERSION                canonical application version
```

## Prerequisites

- Python 3.12 exactly for direct backend development.
- Node.js 22 and npm.
- Docker Engine with Docker Compose v2.

The repository includes `.python-version`. Backend metadata rejects Python 3.13
and newer.

## Local quick start

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec backend alembic upgrade head
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
```

Local endpoints:

- Frontend: `http://127.0.0.1:5173`
- Backend/OpenAPI: `http://127.0.0.1:8000/docs`
- Grafana: `http://127.0.0.1:3000`
- Prometheus: `http://127.0.0.1:9090`

Create or reuse bounded demo data:

```bash
./scripts/seed-demo.sh
```

The demo covers a local user, manufacturing hierarchy, deterministic readings,
one small model, prediction, and monitoring event. Dataset/RAG demonstrations
are covered by the staging real-backend browser suite.

## Developer setup and validation

Create the Python 3.12 environment and install the hashed development lock:

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install --require-hashes \
  -r backend/requirements/dev.lock
backend/.venv/bin/python -m pip install --no-deps -e backend
cd frontend && npm ci
```

Fast validation:

```bash
./scripts/validate-release.sh --fast
```

Complete release validation:

```bash
./scripts/validate-release.sh --full
```

The full command covers backend quality/tests/migrations, frontend quality/build
and browser tests, version/document checks, Compose/Nginx configuration, security
scans, SBOM generation, and optional runtime checks when their prerequisites are
available. It reports any deliberately skipped external/runtime checks.

See [development](docs/development.md),
[release readiness](docs/release-readiness.md), and the current
[release validation report](docs/release/release-validation-report.md).

## Dataset, RAG, and chat flow

```text
Create dataset
  → upload immutable CSV or plain-text version
  → worker validates/extracts/chunks
  → ready dataset version
  → attach authorized document version to knowledge base
  → enqueue index build
  → worker creates deterministic 256-dimensional embeddings
  → PostgreSQL pgvector stores and cosine-ranks authorized chunks
  → submit conversation message
  → worker retrieves evidence and creates extractive answer
  → grounded or insufficient-evidence result with persisted citations
```

The local hashing and extractive providers are intentionally deterministic and
network-free. They are not represented as semantic transformer or general LLM
capabilities. See [Data Registry, RAG, and Chatbot Operations](docs/data-rag-operations.md).

## AI lifecycle

Training supports an explicit, allowlisted sklearn plugin catalog for regression
and integer-label classification, plus legacy Random Forest compatibility
endpoints. Background completion creates a candidate. Challenger and champion
assignment require authorized, policy-evaluated, audited operations; controlled
retraining does not auto-promote.

Prediction resolves an exact version or alias and verifies the stored model
contract before inference. Monitoring stores bounded summaries rather than raw
feature matrices. Drift compares a version only with its compatible reference
profile.

Detailed guides:

- [AI Core API](docs/ai-core-api.md)
- [Background training and promotion](docs/ai-background-training-and-promotion.md)
- [Monitoring and drift](docs/ai-prediction-monitoring-and-drift.md)
- [Monitoring orchestration](docs/ai-monitoring-orchestration.md)
- [Controlled retraining](docs/ai-controlled-retraining.md)

## Deployment and recovery

The supported pilot deployment is the reviewed single-VM Compose path:

```bash
./scripts/deploy-production.sh --env-file .env.production --https
./scripts/verify-production.sh --env-file .env.production --https
```

Only Nginx publishes application traffic in the production overlay. Backend,
worker, frontend, and reverse proxy run non-root with read-only root filesystems.
API documentation is disabled and production settings require injected secrets,
explicit CORS origins, and proxy configuration.

Back up PostgreSQL and the immutable dataset volume as a paired, checksummed set:

```bash
./scripts/backup-postgres.sh
./scripts/verify-postgres-backup.sh \
  backups/postgres/postgres-YYYYmmddTHHMMSSZ.dump
```

Local volumes are not off-host backups. Follow
[backups and disaster recovery](docs/backups-and-disaster-recovery.md) and the
[Google Cloud single-VM deployment guide](docs/google-cloud-production-deployment.md).

## Release governance

- [Repository audit](docs/release/repository-audit.md)
- [Supported scope](docs/release/supported-scope.md)
- [Versioning policy](docs/release/versioning-policy.md)
- [Performance budget](docs/release/performance-budget.md)
- [Security exception register](docs/security/security-exception-register.md)
- [Legal readiness](docs/release/legal-readiness-checklist.md)
- [Release checklist](docs/release-checklist.md)
- [Validation evidence](docs/release/release-validation-report.md)

The root `VERSION` file is canonical. Final tags use `vX.Y.Z`; Docker images are
not currently published by repository automation.
