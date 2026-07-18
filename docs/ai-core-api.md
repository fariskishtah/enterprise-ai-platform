# AI Core API

This guide documents the compatible synchronous AI Core HTTP boundary. Persistent
background jobs and controlled promotion are documented in
[AI Background Training and Model Promotion](ai-background-training-and-promotion.md),
and event, quality, and drift APIs are documented in
[AI Prediction Monitoring and Drift](ai-prediction-monitoring-and-drift.md). The
interactive OpenAPI UI is available at `http://localhost:8000/docs` outside the
production environment.

## Overview

The current request path is explicit:

```text
HTTP Request
  → Transport Validation
  → NumPy Conversion
  → Typed Training Plan
  → Local TrainingEngine
  → Metrics
  → Local Artifact
  → MLflow Tracking
  → Model Registry
  → Registered Prediction
```

Training validates the HTTP payload, converts prepared values to the platform's
exact NumPy contracts, fits and evaluates a model locally, persists a Joblib
artifact, records a completed MLflow run, and creates an immutable registered
model version. Prediction resolves an exact version or existing alias and loads
that registered artifact; it does not train a new model.

The API currently supports only Random Forest regression and integer-label
classification.

## Authentication and roles

All AI Core endpoints require a JWT access token:

```http
Authorization: Bearer <token>
```

To create an operator account, call the public registration endpoint with an
email and a password that satisfies the documented password policy:

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"<email>","password":"<strong-password>"}'
```

Then obtain an access and refresh token pair:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"<email>","password":"<password>"}'
```

The login response contains `access_token`, `refresh_token`, `token_type`, and
`expires_in`. Copy the access token for the examples below:

```bash
export ACCESS_TOKEN="<access_token>"
export API_BASE_URL="http://localhost:8000"
```

Public registration always creates an `operator`. It does not provide role
elevation. An admin or engineer account must be provisioned through the
environment's authorized administrative process before using training endpoints.
The repository deliberately does not ship default credentials.

| Role | Train | Predict | Resolve model version |
| --- | --- | --- | --- |
| Admin | Yes | Yes | Yes |
| Engineer | Yes | Yes | Yes |
| Operator | No | Yes | Yes |

## Regression training

`POST /ai/training/random-forest/regression` accepts a finite rectangular feature
matrix and one finite numeric target per row. Transport values are converted to
two-dimensional float64 features and one-dimensional float64 targets. The
evaluation set is not used for fitting; it produces the returned regression
metrics.

From the repository root:

```bash
curl -X POST \
  "${API_BASE_URL}/ai/training/random-forest/regression" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  --data @examples/ai-core/regression-training-request.json
```

Equivalent body:

```json
{
  "training_features": [
    [0.0, 1.0],
    [1.0, 1.5],
    [2.0, 2.0],
    [3.0, 2.5]
  ],
  "training_targets": [1.0, 2.0, 3.0, 4.0],
  "evaluation_features": [
    [0.5, 1.25],
    [2.5, 2.25]
  ],
  "evaluation_targets": [1.5, 3.5],
  "hyperparameters": {
    "n_estimators": 5,
    "n_jobs": 1
  },
  "random_seed": 17,
  "experiment_name": "AI Core Manual Demo",
  "run_name": "regression-demo",
  "registered_model_name": "ai_core_random_forest_regression",
  "tags": {
    "purpose": "manual-demo"
  }
}
```

Successful training returns `201 Created`. Values vary by execution and library
version, so the following shows the response shape rather than promised metric
values:

```json
{
  "run_id": "3f9655cb-8778-45e9-81e8-4566286200fb",
  "trainer_key": {
    "algorithm": "random_forest",
    "task_type": "regression"
  },
  "metrics": {
    "mae": 0.0,
    "mse": 0.0,
    "rmse": 0.0,
    "r2": 0.0
  },
  "mlflow_experiment_id": "<experiment-id>",
  "mlflow_run_id": "<run-id>",
  "mlflow_artifact_uri": "<mlflow-artifact-uri>",
  "registered_model_name": "ai_core_random_forest_regression",
  "registered_model_version": "1",
  "duration_seconds": 0.0
}
```

`run_id` is the platform execution UUID. The three `mlflow_*` fields identify the
completed MLflow experiment, run, and exact `model/model.joblib` artifact.
`registered_model_version` is a newly created immutable version. No local
artifact-manager filesystem path is returned.

## Classification training

`POST /ai/training/random-forest/classification` uses finite numeric features and
strict integer class labels. Features become float64; targets become int64. There
must be one label per feature row, and training data must contain at least two
classes.

```bash
curl -X POST \
  "${API_BASE_URL}/ai/training/random-forest/classification" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  --data @examples/ai-core/classification-training-request.json
```

```json
{
  "training_features": [
    [0.0, 0.5],
    [0.5, 1.0],
    [2.5, 2.0],
    [3.0, 2.5]
  ],
  "training_targets": [0, 0, 1, 1],
  "evaluation_features": [
    [0.25, 0.75],
    [2.75, 2.25]
  ],
  "evaluation_targets": [0, 1],
  "hyperparameters": {
    "n_estimators": 5,
    "n_jobs": 1
  },
  "random_seed": 19,
  "experiment_name": "AI Core Manual Demo",
  "run_name": "classification-demo",
  "registered_model_name": "ai_core_random_forest_classification",
  "tags": {
    "purpose": "manual-demo"
  }
}
```

The successful response uses the same training envelope as regression, with
`task_type` set to `classification` and the classification metric keys documented
below.

## Registered prediction

Prediction accepts the registered model name, an exact positive version or
existing alias, and a rectangular finite numeric feature matrix. The response
always reports the exact resolved version.

### Regression by exact version

```bash
curl -X POST \
  "${API_BASE_URL}/ai/predictions/random-forest/regression" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  --data @examples/ai-core/regression-prediction-request.json
```

```json
{
  "model_name": "ai_core_random_forest_regression",
  "model_version": "1",
  "trainer_key": {
    "algorithm": "random_forest",
    "task_type": "regression"
  },
  "predictions": [1.25, 3.5]
}
```

### Classification by exact version

```bash
curl -X POST \
  "${API_BASE_URL}/ai/predictions/random-forest/classification" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  --data @examples/ai-core/classification-prediction-request.json
```

```json
{
  "model_name": "ai_core_random_forest_classification",
  "model_version": "1",
  "trainer_key": {
    "algorithm": "random_forest",
    "task_type": "classification"
  },
  "predictions": [0, 1]
}
```

To predict through an alias, replace `version_or_alias` with an assigned safe
alias such as `champion`. Successful background training assigns `candidate`;
authorized promotion endpoints assign `challenger` and `champion` explicitly.

## Model-version lookup

Resolve exact registry metadata without loading the artifact:

```bash
curl \
  "${API_BASE_URL}/ai/models/ai_core_random_forest_regression/versions/1" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"
```

An existing alias can replace `1` in the URL. The response identifies the exact
version and source MLflow run:

```json
{
  "model_name": "ai_core_random_forest_regression",
  "model_version": "1",
  "run_id": "<mlflow-run-id>",
  "trainer_key": {
    "algorithm": "random_forest",
    "task_type": "regression"
  },
  "status": "READY",
  "aliases": ["champion"]
}
```

Aliases may be empty. Lookup does not assign aliases, download a model, or change
registry state.

## Hyperparameter reference

The HTTP and internal parameter models intentionally expose a narrower contract
than the complete scikit-learn Random Forest API. Unsupported fields are rejected;
values are not implicitly expanded into other scikit-learn forms.

### Shared parameters

| Field | Accepted values | Default | Meaning |
| --- | --- | --- | --- |
| `n_estimators` | Strict integer `> 0` | `100` | Number of trees. |
| `max_depth` | Strict integer `> 0` or `null` | `null` | Maximum tree depth. |
| `min_samples_split` | Strict integer `>= 2` | `2` | Minimum samples required to split a node. |
| `min_samples_leaf` | Strict integer `> 0` | `1` | Minimum samples required at a leaf. |
| `max_features` | `"sqrt"`, `"log2"`, or strict float in `(0, 1]` | Task-specific | Features considered per split. Integer counts are not accepted. |
| `bootstrap` | Strict JSON boolean | `true` | Fit trees from bootstrap samples. |
| `n_jobs` | Strict non-zero integer or `null` | `null` | Parallel worker count passed to the estimator. |
| `random_state` | Strict integer or `null` | `null` | Estimator seed when no workflow seed is supplied. |

### Regression criterion

Supported `criterion` values are `squared_error`, `absolute_error`,
`friedman_mse`, and `poisson`. The default is `squared_error`.

Regression `max_features` defaults to the fractional float `1.0`.

### Classification criterion

Supported `criterion` values are `gini`, `entropy`, and `log_loss`. The default is
`gini`.

Classification `max_features` defaults to `sqrt`.

### Seed precedence

The request-level `random_seed` is the workflow seed. When it is not `null`, it
overrides `hyperparameters.random_state` for estimator construction. When it is
`null`, `hyperparameters.random_state` is used. When both are `null`, the estimator
uses its unseeded default.

## Metrics reference

Regression responses contain:

| Key | Meaning |
| --- | --- |
| `mae` | Mean absolute error. |
| `mse` | Mean squared error. |
| `rmse` | Square root of MSE. |
| `r2` | Coefficient of determination (R²). |

Classification responses contain:

| Key | Meaning |
| --- | --- |
| `accuracy` | Fraction of labels predicted correctly. |
| `precision_macro` | Unweighted mean of per-class precision. |
| `recall_macro` | Unweighted mean of per-class recall. |
| `f1_macro` | Unweighted mean of per-class F1. |

Macro averaging gives every observed class equal weight, regardless of class
frequency. Undefined per-class classification scores contribute zero.

## Failure behavior

- A local training or evaluation failure stops before MLflow tracking and model
  registration.
- A tracking failure preserves the already-created local Joblib artifact and does
  not attempt registration.
- A registry failure preserves both the local artifact and the completed MLflow
  run.
- Completed stages are not rolled back automatically.
- Prediction validates the resolved `TrainerKey` before downloading or
  deserializing the fitted model.
- A runtime model-type mismatch stops prediction before inference.
- External MLflow registry, tracking, or artifact failures return a sanitized
  `502 Bad Gateway` response. Internal exception details are not returned.

Documented statuses are:

| Status | Meaning |
| --- | --- |
| `401` | Bearer access token is missing or invalid. |
| `403` | Account is inactive or its role is not permitted. |
| `404` | Requested registered model version or alias does not exist. |
| `409` | Artifact, trainer identity, model type, or registry metadata conflict. |
| `422` | Transport or AI platform input validation failed. |
| `502` | Sanitized external MLflow or artifact-service failure. |

## Current limitations

Training request limits are shared by synchronous and background endpoints:
10,000 training rows, 5,000 evaluation rows, 256 feature columns, 1,000,000
combined feature cells, 32 tags, 250-character tag keys, 5,000-character tag
values, 255-character run names, and 5,000-character model descriptions. These
are intentional MVP platform limits rather than the complete capacities of
scikit-learn or MLflow.

- Training and prediction run synchronously in the API process.
- Random Forest is the only algorithm.
- Internal features are exact two-dimensional float64 arrays.
- Regression targets and predictions are exact one-dimensional float64 arrays.
- Classification targets and predictions are exact one-dimensional int64 labels.
- Classification probability prediction is not exposed.
- Background jobs use a dedicated worker; synchronous compatibility endpoints
  still run in the API process.
- Model promotion is explicit and audited, not automated.
- Prediction event summaries, operational/data-quality monitoring, and
  exact-version drift are documented in
  [AI Prediction Monitoring and Drift](ai-prediction-monitoring-and-drift.md).
- Automated drift alerts are not implemented.
- Automated retraining is not implemented.
- Production cloud deployment is not implemented.
