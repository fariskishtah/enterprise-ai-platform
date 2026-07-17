# AI Manufacturing Platform

Production-grade monorepo foundation for an AI Manufacturing Platform. Sprint 1 created the platform skeleton, Sprint 2 added authentication and user management, Sprint 3 added the core manufacturing domain, Sprint 4 added sensor management, Sprint 5 added the backend sensor data platform, Sprint 6 added CSV ETL and data validation, Sprint 7 added backend feature engineering dataset exports, and Sprint 8 adds MLOps experiment management infrastructure. The project still does not include ML models, model training, prediction, RAG, computer vision, MQTT, or Kafka.

## Project Overview

The repository is split into independently owned areas for the backend API, frontend web app, ML assets, infrastructure, Docker assets, datasets, documentation, tests, and automation scripts.

The backend is a FastAPI service using typed environment configuration, SQLAlchemy 2.0, Alembic, Pydantic v2, Pytest, Ruff, Black, and mypy. It includes JWT access tokens, refresh-token rotation, pwdlib password hashing, UUID primary keys, role-based access control, production CRUD APIs for companies, factories, machines, and sensors, sensor readings and upload-job APIs, CSV ETL using Polars and Pandera, Polars-based feature dataset exports to versioned Parquet files, and MLOps metadata management with MLflow, YAML configuration, and Optuna study preparation. The frontend is a Vite React TypeScript app using TailwindCSS, React Router, ESLint, and Prettier.

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

## How To Run

Create a local environment file:

```bash
cp .env.example .env
```

Run the full stack:

```bash
docker compose up --build
```

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

## Docker Commands

```bash
docker compose up --build
docker compose down
docker compose logs -f backend
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
```

## Development Workflow

Bootstrap local dependencies:

```bash
./scripts/bootstrap.sh
```

Run all local checks:

```bash
./scripts/check.sh
```

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
- Refresh tokens are stored as SHA-256 digests and rotated on refresh so logout and token reuse detection are enforceable server-side.
- Passwords are hashed with pwdlib using Argon2 through the recommended password hash profile.
- The frontend uses React Router immediately so route ownership is explicit even with only the Dashboard page.
- CI runs backend linting, formatting, type checking, and tests, plus frontend lint, build, formatting, and audit checks before changes can merge.
