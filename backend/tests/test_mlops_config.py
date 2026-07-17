"""MLOps configuration tests."""

from pathlib import Path

import pytest
from app.config.mlops import (
    MLOpsConfigurationLoader,
    OptunaConfiguration,
    OptunaDirection,
)
from app.services.exceptions import InvalidMLOpsConfigurationError
from app.services.optuna import OptunaStudyFactory


def test_training_run_configuration_loads_from_yaml(tmp_path: Path) -> None:
    """Training-run parameters load from YAML configuration."""
    config_path = tmp_path / "training.yaml"
    config_path.write_text(
        "\n".join(
            [
                "dataset_version: dataset_v1",
                "algorithm: baseline-regressor",
                "parameters:",
                "  rolling_window: 5",
                "  lag_features:",
                "    - lag_1",
                "    - lag_5",
                "metrics:",
                "  rmse: 1.25",
                "optuna:",
                "  enabled: true",
                "  study_name: baseline-study",
                "  direction: minimize",
                "  n_trials: 10",
            ],
        ),
        encoding="utf-8",
    )

    config = MLOpsConfigurationLoader(config_dir=tmp_path).load_training_run_config(
        "training.yaml",
    )

    assert config.dataset_version == "dataset_v1"
    assert config.algorithm == "baseline-regressor"
    assert config.parameters["rolling_window"] == 5
    assert config.metrics["rmse"] == 1.25
    assert config.optuna.enabled is True
    assert config.optuna.direction == OptunaDirection.MINIMIZE


def test_training_run_configuration_rejects_invalid_yaml(tmp_path: Path) -> None:
    """Invalid YAML configurations fail clearly."""
    config_path = tmp_path / "training.yaml"
    config_path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    loader = MLOpsConfigurationLoader(config_dir=tmp_path)

    with pytest.raises(InvalidMLOpsConfigurationError):
        loader.load_training_run_config(config_path)


def test_training_run_configuration_rejects_wrong_extension(tmp_path: Path) -> None:
    """Configuration files must use YAML extensions."""
    config_path = tmp_path / "training.json"
    config_path.write_text("{}", encoding="utf-8")

    loader = MLOpsConfigurationLoader(config_dir=tmp_path)

    with pytest.raises(InvalidMLOpsConfigurationError):
        loader.load_training_run_config(config_path)


def test_optuna_factory_creates_configured_study_without_trials() -> None:
    """Optuna integration is configured without running optimization."""
    factory = OptunaStudyFactory(default_storage_url=None)
    study = factory.create_study(
        OptunaConfiguration(
            enabled=True,
            study_name="sprint-8-study",
            direction=OptunaDirection.MAXIMIZE,
        ),
    )

    assert study.study_name == "sprint-8-study"
    assert len(study.trials) == 0
