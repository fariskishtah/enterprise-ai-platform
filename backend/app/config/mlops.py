"""YAML-backed MLOps configuration models."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    PositiveInt,
    StringConstraints,
    ValidationError,
    model_validator,
)

from app.services.exceptions import InvalidMLOpsConfigurationError
from app.utils.json_validation import ensure_json_serializable

ConfigText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class OptunaDirection(StrEnum):
    """Supported Optuna study directions."""

    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"


class OptunaConfiguration(BaseModel):
    """Optuna study configuration loaded from YAML."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    study_name: ConfigText | None = Field(default=None)
    direction: OptunaDirection = OptunaDirection.MINIMIZE
    storage_url: ConfigText | None = Field(default=None)
    n_trials: PositiveInt | None = Field(default=None)


class TrainingRunConfiguration(BaseModel):
    """Validated training-run configuration loaded from YAML."""

    model_config = ConfigDict(frozen=True)

    dataset_version: ConfigText
    algorithm: ConfigText
    parameters: dict[str, object] = Field(default_factory=dict)
    metrics: dict[str, FiniteFloat] = Field(default_factory=dict)
    optuna: OptunaConfiguration = Field(default_factory=OptunaConfiguration)

    @model_validator(mode="after")
    def require_serializable_payload(self) -> Self:
        """Require JSON-safe parameters and metrics."""
        ensure_json_serializable(self.parameters, field_name="parameters")
        ensure_json_serializable(self.metrics, field_name="metrics")
        return self


class MLOpsConfigurationLoader:
    """Load and validate MLOps YAML configuration files."""

    def __init__(self, *, config_dir: Path | str) -> None:
        self._config_dir = Path(config_dir)

    def load_training_run_config(
        self,
        config_path: Path | str,
    ) -> TrainingRunConfiguration:
        """Load a training-run configuration from a YAML file."""
        resolved_path = self._resolve_config_path(config_path)
        if resolved_path.suffix.lower() not in {".yaml", ".yml"}:
            raise InvalidMLOpsConfigurationError(
                "MLOps configuration files must use .yaml or .yml.",
            )
        if not resolved_path.is_file():
            raise InvalidMLOpsConfigurationError("MLOps configuration file not found.")

        with resolved_path.open("r", encoding="utf-8") as config_file:
            raw_config = yaml.safe_load(config_file)
        if not isinstance(raw_config, dict):
            raise InvalidMLOpsConfigurationError(
                "MLOps configuration must be a YAML mapping.",
            )

        try:
            return TrainingRunConfiguration.model_validate(raw_config)
        except ValidationError as exc:
            raise InvalidMLOpsConfigurationError(str(exc)) from exc

    def _resolve_config_path(self, config_path: Path | str) -> Path:
        path = Path(config_path)
        if path.is_absolute():
            return path
        return self._config_dir / path
