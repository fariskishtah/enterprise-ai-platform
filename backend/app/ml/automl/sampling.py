"""Dependency-light deterministic sampling for plugin-owned search spaces."""

from __future__ import annotations

import json
import math
import random
from decimal import Decimal
from hashlib import sha256

from app.ml.automl.models import AutoMLTrialSpecification, parameter_fingerprint
from app.ml.automl.search_space import (
    CategoricalSearchParameter,
    IntegerSearchParameter,
    PluginAutoMLSearchSpace,
    SearchParameter,
    validate_narrowed_search_space,
)
from app.ml.plugins.core import ModelPlugin


def search_space_fingerprint(search_space: PluginAutoMLSearchSpace) -> str:
    """Return a canonical digest of one immutable plugin search space."""
    canonical = json.dumps(
        search_space.model_dump(mode="json"),
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def derive_trial_seed(
    *, study_seed: int, plugin_id: str, trial_number: int, space_fingerprint: str
) -> int:
    """Derive a stable positive 63-bit seed without Python hash randomization."""
    if trial_number < 0:
        raise ValueError("Trial number must be non-negative.")
    payload = json.dumps(
        {
            "plugin_id": plugin_id,
            "search_space": space_fingerprint,
            "study_seed": study_seed,
            "trial_number": trial_number,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return int.from_bytes(sha256(payload.encode("utf-8")).digest()[:8], "big") & (
        2**63 - 1
    )


def sample_plugin_trial(
    *,
    plugin: ModelPlugin,
    study_seed: int,
    trial_number: int,
    search_space: PluginAutoMLSearchSpace | None = None,
) -> AutoMLTrialSpecification:
    """Sample and revalidate one deterministic trial for an AutoML plugin."""
    plugin_owned = plugin.automl_search_space
    if plugin_owned is None:
        raise ValueError("The plugin does not support AutoML.")
    owned = search_space or plugin_owned
    validate_narrowed_search_space(plugin_owned, owned)
    plugin.validate_automl_search_space(owned)
    fingerprint = search_space_fingerprint(owned)
    seed = derive_trial_seed(
        study_seed=study_seed,
        plugin_id=plugin.id,
        trial_number=trial_number,
        space_fingerprint=fingerprint,
    )
    generator = random.Random(seed)
    sampled = {
        parameter.name: _sample_parameter(parameter, generator)
        for parameter in sorted(owned.parameters, key=lambda item: item.name)
    }
    plugin.validate_parameters(sampled)
    canonical = dict(sorted(sampled.items()))
    return AutoMLTrialSpecification(
        study_seed=study_seed,
        trial_number=trial_number,
        plugin_id=plugin.id,
        sampled_parameters=canonical,
        trial_seed=seed,
        parameter_fingerprint=parameter_fingerprint(canonical),
    )


def _sample_parameter(
    parameter: SearchParameter, generator: random.Random
) -> bool | int | float | str:
    if isinstance(parameter, IntegerSearchParameter):
        count = (parameter.high - parameter.low) // parameter.step
        return parameter.low + generator.randint(0, count) * parameter.step
    if isinstance(parameter, CategoricalSearchParameter):
        return generator.choice(parameter.choices)
    if parameter.log_scale:
        value = math.exp(
            generator.uniform(math.log(parameter.low), math.log(parameter.high))
        )
        return min(max(value, parameter.low), parameter.high)
    if parameter.step is None:
        return generator.uniform(parameter.low, parameter.high)
    low = Decimal(str(parameter.low))
    high = Decimal(str(parameter.high))
    step = Decimal(str(parameter.step))
    count = int((high - low) // step)
    return float(low + step * generator.randint(0, count))
