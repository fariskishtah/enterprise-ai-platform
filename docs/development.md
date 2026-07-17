# Development Guide

## Project Structure

```text
ai-manufacturing-platform/
  backend/          FastAPI backend, Alembic migrations, and backend tests
  frontend/         Vite React TypeScript frontend
  docker/           Dockerfiles
  docs/             Engineering documentation
  scripts/          Local automation
  .github/          CI workflow
```

## Running Locally

```bash
cp .env.example .env
./scripts/bootstrap.sh
```

Backend:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm run dev
```

## Docker

```bash
docker compose up --build
docker compose down
docker compose logs -f backend
```

## Alembic

Run migrations:

```bash
cd backend
alembic upgrade head
```

Inspect the current revision:

```bash
alembic current
```

Create a migration after model changes:

```bash
alembic revision --autogenerate -m "Describe schema change"
```

## Testing

Backend tests:

```bash
cd backend
pytest
```

The backend test suite uses async HTTP clients and an isolated SQLite database for API and service tests.

## Formatting

Backend formatting:

```bash
cd backend
black .
```

Frontend formatting:

```bash
cd frontend
npm run format
```

## Linting

Backend:

```bash
cd backend
ruff check .
mypy app
```

Frontend:

```bash
cd frontend
npm run lint
```

## Pre-commit

Install hooks:

```bash
backend/.venv/bin/pre-commit install --config .pre-commit-config.yaml
```

## CI/CD

GitHub Actions runs:

- Backend Ruff.
- Backend Black check.
- Backend mypy.
- Backend Pytest.
- Frontend ESLint.
- Frontend TypeScript/Vite build.
- Frontend Prettier check.
- Frontend npm audit.

## Development Workflow

1. Create or update SQLAlchemy models and Pydantic schemas.
2. Add repository methods for persistence behavior.
3. Add service-layer use cases and validation.
4. Wire dependencies and route handlers.
5. Add Alembic migrations.
6. Add repository, service, API, RBAC, and validation tests.
7. Update documentation.
8. Run `./scripts/check.sh`.
