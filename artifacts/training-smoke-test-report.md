# Training smoke-test report

The baseline suite passed its bounded background-training, training-engine,
tracked-training, MLflow, retry/reconciliation, monitoring, and retraining smoke
tests on macOS ARM64/CPU. This proves representative small-fixture execution, not
a full production training run. No large model or dataset was downloaded.

The suite reported third-party deprecation warnings from MLflow/Pydantic and
joblib/NumPy; no test failed because of them. A real deployment must run a
bounded job with an approved customer-like dataset and record dataset size,
wall-clock duration, peak worker memory, metrics, cancellation, and artifact
restore before production acceptance.
