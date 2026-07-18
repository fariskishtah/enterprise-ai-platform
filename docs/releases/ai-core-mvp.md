# AI Core MVP — Tracked Training and Registered Prediction

This checkpoint records the first complete AI Core vertical slice in application
version `0.8.0`. It is a capability release note, not a Git tag or a replacement
for the repository's semantic-version changelog.

## Delivered capabilities

- Typed trainer contracts, composite trainer keys, registry, and factory.
- Task-aware Random Forest regression and integer-label classification.
- Exact NumPy feature, target, prediction, and validation boundaries.
- Typed regression and macro-averaged classification metrics.
- Local Joblib persistence with traversal protection and runtime model checks.
- A generic local training engine isolated from HTTP and MLflow.
- MLflow experiment tracking with protected metadata and terminal run states.
- MLflow fitted-model registration with exact artifact URIs.
- Exact model-version and pre-existing alias resolution.
- Registered-model loading and prediction without retraining.
- Authenticated FastAPI training, prediction, and model lookup endpoints.
- Persistent Docker volumes for MLflow and model artifacts.
- Real isolated regression and classification MLflow smoke coverage.

## Quality evidence

The approved milestone was validated with:

- 369 backend tests passed.
- Black passed.
- Ruff passed.
- Strict mypy application checking passed.
- Real regression MLflow training, registration, loading, and prediction passed.
- Real classification MLflow training, registration, loading, and prediction
  passed.

Warning counts are deliberately omitted because they vary with pytest warning
filters and dependency versions.

## Architectural decisions

### Trainer isolation

Each trainer owns only its algorithm identity, fitting, and raw prediction
behavior. The fitted model generic remains strongly typed without requiring the
third-party model object to implement a platform protocol.

### Metrics isolation

Metrics engines consume validated target and prediction arrays and return typed,
immutable reports. Trainers and metrics do not know about HTTP, persistence,
MLflow, or the registry.

### Local engine isolation

The generic `TrainingEngine` sequences trainer resolution, fitting, prediction,
metrics, and local persistence. It remains independent of external tracking and
transport concerns.

### Higher-level tracking service

`TrackedTrainingService` composes successful local execution, MLflow logging, and
model registration. The order is intentional: invalid local training creates no
external run, and a registry version is attempted only after a FINISHED run has
an exact logged artifact URI.

### No cross-system rollback

The current synchronous flow does not fake distributed transactions. A tracking
failure preserves the local artifact. A later registry failure preserves the
local artifact and completed MLflow run. Reconciliation is a future operational
concern.

### Validation before deserialization

Prediction resolves protected registry metadata and validates the composite
`TrainerKey` before it downloads or deserializes Joblib data. This prevents a
known algorithm/task mismatch from crossing the deserialization boundary.

### Typed third-party boundaries

Runtime model-type checks protect Joblib and MLflow artifact boundaries. Narrow
type ignores exist only where third-party packages do not publish typing metadata;
internal application contracts remain strict.

## Known limitations

- Training and prediction are synchronous and execute in the API process.
- Random Forest is the only algorithm family.
- Features use the platform's exact two-dimensional float64 contract.
- Regression targets and predictions are one-dimensional float64 arrays.
- Classification supports only one-dimensional int64 labels and predictions.
- Probability prediction is not exposed.
- Alias assignment and automated model promotion are not implemented.
- Cross-system rollback and reconciliation automation are not implemented.
- Background job execution is not implemented.
- Monitoring and drift detection are not implemented.
- Automated retraining is not implemented.
- Production cloud deployment is not implemented.
- The local Joblib manager rejects overwrite; production job execution still
  needs same-directory temporary persistence and atomic promotion.

## Next milestone

```text
Background training jobs
  → model promotion workflow
  → monitoring and drift detection
  → automated retraining policy
```

These items describe the intended sequence only; none is implemented by this
checkpoint.
