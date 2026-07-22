"""Pure deterministic fair trial materialization from persisted snapshots."""

from dataclasses import dataclass

from app.ml.automl.models import AutoMLTrialSpecification
from app.ml.automl.sampling import sample_plugin_trial
from app.ml.automl.search_space import PluginAutoMLSearchSpace
from app.ml.domain import TaskType
from app.ml.plugins import create_default_plugin_registry


@dataclass(frozen=True, slots=True)
class MaterializationResult:
    """Unique deterministic trials and a bounded exhaustion indicator."""

    trials: tuple[AutoMLTrialSpecification, ...]
    exhausted: bool


def materialize_trials(
    *,
    task_type: TaskType,
    plugin_ids: tuple[str, ...],
    search_spaces: tuple[PluginAutoMLSearchSpace, ...],
    study_seed: int,
    trial_budget: int,
) -> MaterializationResult:
    """Allocate trial numbers round-robin across plugins and skip duplicates."""
    if not 1 <= trial_budget <= 100:
        raise ValueError("AutoML trial budget must be between 1 and 100.")
    if not plugin_ids:
        raise ValueError("AutoML materialization requires at least one plugin.")
    spaces = {space.plugin_id: space for space in search_spaces}
    if set(spaces) != set(plugin_ids):
        raise ValueError("Every AutoML plugin requires one search-space snapshot.")
    registry = create_default_plugin_registry()
    fingerprints: set[str] = set()
    trials: list[AutoMLTrialSpecification] = []
    for trial_number in range(trial_budget):
        plugin_id = plugin_ids[trial_number % len(plugin_ids)]
        plugin = registry.get(plugin_id, task_type)
        trial = sample_plugin_trial(
            plugin=plugin,
            study_seed=study_seed,
            trial_number=trial_number,
            search_space=spaces[plugin_id],
        )
        scoped = f"{plugin_id}:{trial.parameter_fingerprint}"
        if scoped in fingerprints:
            continue
        fingerprints.add(scoped)
        trials.append(trial)
    return MaterializationResult(tuple(trials), len(trials) < trial_budget)
