# Development Guide

The supported backend interpreter is Python 3.12. The repository deliberately rejects
Python 3.13 and later until compatibility is validated. With `pyenv`, the root
`.python-version` selects the supported interpreter.

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
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements/dev.lock
python -m pip install --no-deps --no-build-isolation -e .
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
python --version  # must report Python 3.12.x
pytest -q
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
- Secret, dependency, SAST, container, SBOM, and license checks.

Backend dependencies are resolved from `pyproject.toml` and committed as hashed
`requirements/base.lock` and `requirements/dev.lock` files. Regenerate both intentionally
with the Python 3.12 lock environment documented in the root README; do not hand-edit
lock entries.

## Development Workflow

1. Create or update SQLAlchemy models and Pydantic schemas.
2. Add repository methods for persistence behavior.
3. Add service-layer use cases and validation.
4. Wire dependencies and route handlers.
5. Add Alembic migrations.
6. Add repository, service, API, RBAC, and validation tests.
7. Update documentation.
8. Run `./scripts/validate-release.sh --fast`.
9. Before a release candidate, run `./scripts/validate-release.sh --full`.
