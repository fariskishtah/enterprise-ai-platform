"""Optuna integration helpers for future optimization workflows."""

from __future__ import annotations

import optuna

from app.config.mlops import OptunaConfiguration
from app.services.exceptions import InvalidMLOpsConfigurationError


class OptunaStudyFactory:
    """Create configured Optuna studies without executing optimization."""

    def __init__(self, *, default_storage_url: str | None) -> None:
        self._default_storage_url = default_storage_url

    def create_study(self, config: OptunaConfiguration) -> optuna.Study:
        """Create or load a study from validated configuration."""
        if not config.enabled:
            raise InvalidMLOpsConfigurationError(
                "Optuna configuration must be enabled before creating a study.",
            )
        storage_url = config.storage_url or self._default_storage_url
        return optuna.create_study(
            direction=config.direction.value,
            study_name=config.study_name,
            storage=storage_url,
            load_if_exists=True,
        )
