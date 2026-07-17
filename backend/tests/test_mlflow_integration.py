"""MLflow model registry integration tests."""

from pathlib import Path
from uuid import uuid4

from app.models.mlops import TrainingRunStatus
from app.services.model_registry import MLflowModelRegistry
from mlflow.tracking import MlflowClient


def test_mlflow_registry_records_experiment_run_and_artifact_metadata(
    tmp_path: Path,
) -> None:
    """MLflow adapter records metadata without training a model."""
    tracking_uri = f"file:{tmp_path / 'mlruns'}"
    registry = MLflowModelRegistry(
        tracking_uri=tracking_uri,
        artifact_root=tmp_path / "artifacts",
    )
    experiment_name = "Sprint 8 MLflow Experiment"
    training_run_id = uuid4()
    artifact_id = uuid4()

    experiment_id = registry.ensure_experiment(
        name=experiment_name,
        description="Metadata-only integration test",
    )
    run_id = registry.create_training_run(
        experiment_name=experiment_name,
        training_run_id=training_run_id,
        dataset_version="dataset_v1",
        algorithm="baseline-regressor",
        parameters={"rolling_window": 5, "features": ["mean", "lag_1"]},
        metrics={"rmse": 1.25},
        status=TrainingRunStatus.PENDING,
    )
    registry.register_model_artifact(
        experiment_name=experiment_name,
        training_run_id=training_run_id,
        model_artifact_id=artifact_id,
        framework="sklearn",
        model_type="metadata-only",
        version="v1",
        artifact_path="s3://models/sprint-8/v1/model.pkl",
        checksum="d" * 64,
    )

    client = MlflowClient(tracking_uri=tracking_uri)
    experiment = client.get_experiment(experiment_id)
    run = client.get_run(run_id)
    artifact_prefix = f"platform_artifact_{str(artifact_id)}"

    assert experiment.name == experiment_name
    assert run.data.tags["platform_training_run_id"] == str(training_run_id)
    assert run.data.tags["platform_dataset_version"] == "dataset_v1"
    assert run.data.params["rolling_window"] == "5"
    assert run.data.metrics["rmse"] == 1.25
    assert run.data.tags[f"{artifact_prefix}_version"] == "v1"
    assert run.data.tags[f"{artifact_prefix}_checksum"] == "d" * 64
