# AI Core Local Demo

This guide demonstrates synchronous Random Forest training, MLflow tracking,
model registration, registered prediction, and model-version lookup from a local
checkout. The dedicated worker and governance flow is documented in
[AI Background Training and Model Promotion](ai-background-training-and-promotion.md).
Monitoring operations are documented in
[AI Prediction Monitoring and Drift](ai-prediction-monitoring-and-drift.md).
Controlled candidate reruns are documented in
[Controlled Automated Retraining](ai-controlled-retraining.md).
Run commands from the repository root unless a step says otherwise.

## Prerequisites

- Python `>=3.12,<3.13` for direct backend execution. The project and backend
  image currently use Python 3.12.
- Docker with the Compose plugin for the full-stack path, or locally reachable
  PostgreSQL and Redis services for direct backend execution.
- `curl` for manual API requests.
- An authorized admin or engineer account for training. Prediction and model
  lookup also permit operators.

The MLflow adapter uses a file tracking store. It does not require a separate
MLflow server for this milestone. Docker stores MLflow data and Joblib artifacts
in named volumes; direct Python execution uses the relative paths from
`.env.example`.

## Environment setup

Create the local environment file:

```bash
cp .env.example .env
```

Before starting services, replace the example `SECRET_KEY` in `.env` with a new
development-only random value. One way to generate a value is:

```bash
python3.12 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the generated value into `.env`; never commit it. The example PostgreSQL
password is suitable only for an isolated local environment.

## Docker startup

Build and start the full stack:

```bash
docker compose up --build -d
```

Apply database migrations:

```bash
docker compose exec backend alembic upgrade head
```

Inspect service state and backend logs:

```bash
docker compose ps
docker compose logs --tail=100 backend
docker compose logs --tail=100 training-worker
curl http://localhost:8000/health
```

OpenAPI documentation is available at `http://localhost:8000/docs` while
`ENVIRONMENT` is not `production`.

The backend image runs from `/app`. Compose injects these explicit persistent
paths:

| Container path | Named volume | Purpose |
| --- | --- | --- |
| `/app/data/mlflow` | `mlflow-data` | MLflow experiments, runs, registry metadata, and logged artifacts. |
| `/app/data/model-artifacts` | `model-artifact-data` | Existing MLOps model-artifact storage. |
| `/app/data/ai-artifacts` | `ai-artifact-data` | Local AI Core Joblib artifacts. |

Container replacement does not delete these named volumes.

## Local non-Docker backend startup

The repository bootstrap script creates the Python 3.12 virtual environment and
installs development dependencies:

```bash
./scripts/bootstrap.sh
```

Alternatively, bootstrap only the backend:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements/dev.lock
python -m pip install --no-deps --no-build-isolation -e .
cd ..
```

Start PostgreSQL and Redis locally. They can be the repository's containers:

```bash
docker compose up -d postgres redis
```

The root `.env` uses Docker service hostnames. A backend process running directly
on the host must override those two URLs with host-reachable values. With the
default Compose ports and local-only example credentials:

```bash
export DATABASE_URL="postgresql+psycopg://ai_manufacturing:ai_manufacturing_password@localhost:5432/ai_manufacturing"
export REDIS_URL="redis://localhost:6379/0"
export SECRET_KEY="<generated-development-secret>"
```

Apply migrations and run the server:

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
uvicorn app.main:app --reload
```

From `backend/`, the default direct-execution stores resolve to `../mlruns`,
`../ml/model-artifacts`, and `../ml/ai-artifacts` as documented in `.env.example`.

## Authentication setup

Public registration creates only an operator:

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"<email>","password":"<strong-password>"}'
```

Login returns an access and refresh token pair:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"<email>","password":"<password>"}'
```

Set the returned access token:

```bash
export API_BASE_URL="http://localhost:8000"
export ACCESS_TOKEN="<access_token>"
```

Operators may predict and resolve model metadata, but training requires an admin
or engineer. Use an account provisioned by the environment's authorized
administrative process. There is intentionally no public role-elevation endpoint,
default administrative credential, or role-seeding command in this repository.

For an isolated automated demonstration when no administrative account has been
provisioned, the focused API tests create role-specific users through development
fixtures in a temporary database:

```bash
cd backend
.venv/bin/pytest -q tests/test_ai_api_training.py tests/test_ai_api_prediction.py
```

That fixture behavior is test-only and does not modify the running local database.

## Full demonstration sequence

The following manual flow assumes `ACCESS_TOKEN` belongs to an admin or engineer.

### 1. Start services

Use the Docker or direct backend startup above and verify `/health` returns `200`.

### 2. Obtain a token

Log in and export the returned `access_token` as shown above.

### 3. Train a regression model

```bash
curl -X POST \
  "${API_BASE_URL}/ai/training/random-forest/regression" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  --data @examples/ai-core/regression-training-request.json
```

### 4. Capture the registered model reference

Record `registered_model_name` and `registered_model_version` from the `201`
response. With a new local store, the example normally creates version `1`, but
always use the version actually returned.

### 5. Predict with the regression model

Update `version_or_alias` in
`examples/ai-core/regression-prediction-request.json` if the returned version is
not `1`, then run:

```bash
curl -X POST \
  "${API_BASE_URL}/ai/predictions/random-forest/regression" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  --data @examples/ai-core/regression-prediction-request.json
```

### 6. Train a classification model

```bash
curl -X POST \
  "${API_BASE_URL}/ai/training/random-forest/classification" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  --data @examples/ai-core/classification-training-request.json
```

Record the returned classification model name and version.

### 7. Predict with the classification model

Update the example version when necessary, then run:

```bash
curl -X POST \
  "${API_BASE_URL}/ai/predictions/random-forest/classification" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  --data @examples/ai-core/classification-prediction-request.json
```

The response contains one integer class label per supplied row. Probability
prediction is not exposed.

### 8. Resolve a registered version

Use the actual model name and version:

```bash
curl \
  "${API_BASE_URL}/ai/models/ai_core_random_forest_regression/versions/1" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"
```

The response includes the exact resolved version, MLflow source run, protected
trainer identity, registration status, and any aliases. An alias may replace `1`
only after it has already been assigned outside this API.

### 9. Inspect MLflow data and local Joblib artifacts

For Docker execution, list a bounded sample of persisted MLflow files:

```bash
docker compose exec backend \
  sh -lc 'find /app/data/mlflow -maxdepth 5 -type f | head -n 30'
```

For direct backend execution, inspect `mlruns/` from the repository root. Each
successful training request produces a FINISHED MLflow run and logs the exact
`model/model.joblib` artifact before registry creation. To inspect the separately
persisted local AI Core artifacts in Docker:

```bash
docker compose exec backend \
  sh -lc 'find /app/data/ai-artifacts -type f -name model.joblib | head -n 20'
```

For direct execution, inspect `ml/ai-artifacts/` from the repository root.

### 10. Query prediction monitoring

After an authenticated prediction, list privacy-preserving event summaries:

```bash
curl "${API_BASE_URL}/ai/monitoring/prediction-events?limit=20" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"
```

Query the exact version or an assigned alias such as `candidate`:

```bash
curl \
  "${API_BASE_URL}/ai/monitoring/models/ai_core_random_forest_regression/versions/candidate/operations" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"

curl \
  "${API_BASE_URL}/ai/monitoring/models/ai_core_random_forest_regression/versions/candidate/drift?minimum_sample_count=1" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"
```

Synchronous compatibility training does not create a background-job evaluation
profile. Use background training for automatic profile creation. A profile may be
temporarily missing after noncritical monitoring failure; reconcile from the
persisted bounded evaluation specification with:

```bash
docker compose exec training-worker python -m app.ml.monitoring.reconcile
```

### 11. Confirm persistent volumes

```bash
docker volume ls --filter name=ai-manufacturing-platform
docker volume inspect ai-manufacturing-platform_mlflow-data
docker volume inspect ai-manufacturing-platform_ai-artifact-data
```

Compose prefixes volume names with the project name by default. A custom Compose
project name changes that prefix.

## Cleanup

Stop and remove containers while preserving named volumes:

```bash
docker compose down
```

To also delete PostgreSQL, Redis, MLflow, and model-artifact volume data:

```bash
docker compose down -v
```

`docker compose down -v` is destructive. It deletes the persisted MLflow runs,
registered model metadata, local Joblib artifacts, application database, and Redis
data owned by this Compose project. Use it only when a complete reset is intended.

Prediction-event cleanup is separate from Compose teardown. Preview it with
`python -m app.ml.monitoring.retention --dry-run`; `--execute` deletes only one
configured batch of expired events and leaves jobs, audits, profiles, and model
artifacts intact. No cleanup schedule is installed by this milestone.
