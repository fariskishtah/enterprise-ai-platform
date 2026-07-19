"""Explicit JSON serialization for immutable monitoring records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.ml.monitoring.exceptions import MonitoringDataError
from app.ml.monitoring.models import (
    ClassificationPredictionProfile,
    ClassificationPredictionReferenceProfile,
    FeatureReferenceProfile,
    FeatureRequestProfile,
    NumericReferenceProfile,
    NumericSummary,
    PredictionReferenceProfile,
    PredictionRequestProfile,
    RegressionPredictionProfile,
    RegressionPredictionReferenceProfile,
)


def feature_request_profiles_payload(
    profiles: Sequence[FeatureRequestProfile],
) -> list[dict[str, object]]:
    """Serialize request feature summaries for a JSON column."""
    return [
        {
            "feature_index": profile.feature_index,
            "summary": numeric_summary_payload(profile.summary),
            "reference_bin_counts": (
                list(profile.reference_bin_counts)
                if profile.reference_bin_counts is not None
                else None
            ),
            "out_of_reference_range_count": (profile.out_of_reference_range_count),
        }
        for profile in profiles
    ]


def parse_feature_request_profiles(
    payload: object,
) -> tuple[FeatureRequestProfile, ...]:
    """Parse one persisted request feature profile list."""
    items = _object_sequence(payload, "feature_profile")
    parsed: list[FeatureRequestProfile] = []
    for item in items:
        mapping = _string_mapping(item, "feature profile item")
        raw_bins = mapping.get("reference_bin_counts")
        parsed.append(
            FeatureRequestProfile(
                feature_index=_integer(mapping.get("feature_index"), "feature_index"),
                summary=parse_numeric_summary(mapping.get("summary")),
                reference_bin_counts=(
                    _integer_tuple(raw_bins, "reference_bin_counts")
                    if raw_bins is not None
                    else None
                ),
                out_of_reference_range_count=_integer(
                    mapping.get("out_of_reference_range_count"),
                    "out_of_reference_range_count",
                ),
            ),
        )
    return tuple(parsed)


def prediction_request_profile_payload(
    profile: PredictionRequestProfile,
) -> dict[str, object]:
    """Serialize task-specific request prediction aggregates."""
    if isinstance(profile, RegressionPredictionProfile):
        return {
            "kind": "regression",
            "summary": numeric_summary_payload(profile.summary),
            "reference_bin_counts": (
                list(profile.reference_bin_counts)
                if profile.reference_bin_counts is not None
                else None
            ),
        }
    return {
        "kind": "classification",
        "count": profile.count,
        "class_counts": dict(profile.class_counts),
        "other_count": profile.other_count,
    }


def parse_prediction_request_profile(payload: object) -> PredictionRequestProfile:
    """Parse a persisted request prediction summary."""
    mapping = _string_mapping(payload, "prediction_profile")
    kind = mapping.get("kind")
    if kind == "regression":
        raw_bins = mapping.get("reference_bin_counts")
        return RegressionPredictionProfile(
            summary=parse_numeric_summary(mapping.get("summary")),
            reference_bin_counts=(
                _integer_tuple(raw_bins, "reference_bin_counts")
                if raw_bins is not None
                else None
            ),
        )
    if kind == "classification":
        return ClassificationPredictionProfile(
            count=_integer(mapping.get("count"), "count"),
            class_counts=_string_integer_mapping(
                mapping.get("class_counts"),
                "class_counts",
            ),
            other_count=_integer(mapping.get("other_count"), "other_count"),
        )
    raise MonitoringDataError("Persisted prediction profile kind is invalid.")


def feature_reference_profiles_payload(
    profiles: Sequence[FeatureReferenceProfile],
) -> list[dict[str, object]]:
    """Serialize model-version feature reference distributions."""
    return [
        {
            "feature_index": profile.feature_index,
            "profile": numeric_reference_profile_payload(profile.profile),
        }
        for profile in profiles
    ]


def parse_feature_reference_profiles(
    payload: object,
) -> tuple[FeatureReferenceProfile, ...]:
    """Parse model-version feature reference distributions."""
    parsed: list[FeatureReferenceProfile] = []
    for item in _object_sequence(payload, "feature_profiles"):
        mapping = _string_mapping(item, "feature reference profile")
        parsed.append(
            FeatureReferenceProfile(
                feature_index=_integer(mapping.get("feature_index"), "feature_index"),
                profile=parse_numeric_reference_profile(mapping.get("profile")),
            ),
        )
    return tuple(parsed)


def prediction_reference_profile_payload(
    profile: PredictionReferenceProfile,
) -> dict[str, object]:
    """Serialize an immutable task-specific prediction reference."""
    if isinstance(profile, RegressionPredictionReferenceProfile):
        return {
            "kind": "regression",
            "profile": numeric_reference_profile_payload(profile.profile),
        }
    return {
        "kind": "classification",
        "profile": prediction_request_profile_payload(profile.profile),
    }


def parse_prediction_reference_profile(payload: object) -> PredictionReferenceProfile:
    """Parse one persisted task-specific prediction reference."""
    mapping = _string_mapping(payload, "prediction reference profile")
    kind = mapping.get("kind")
    if kind == "regression":
        return RegressionPredictionReferenceProfile(
            parse_numeric_reference_profile(mapping.get("profile")),
        )
    if kind == "classification":
        parsed = parse_prediction_request_profile(mapping.get("profile"))
        if not isinstance(parsed, ClassificationPredictionProfile):
            raise MonitoringDataError("Classification reference profile is invalid.")
        return ClassificationPredictionReferenceProfile(parsed)
    raise MonitoringDataError("Persisted prediction reference kind is invalid.")


def numeric_summary_payload(summary: NumericSummary) -> dict[str, object]:
    """Serialize safe numeric aggregates."""
    return {
        "count": summary.count,
        "missing_count": summary.missing_count,
        "finite_count": summary.finite_count,
        "minimum": summary.minimum,
        "maximum": summary.maximum,
        "mean": summary.mean,
        "standard_deviation": summary.standard_deviation,
        "quantiles": dict(summary.quantiles),
    }


def parse_numeric_summary(payload: object) -> NumericSummary:
    """Parse safe numeric aggregates from trusted database JSON."""
    mapping = _string_mapping(payload, "numeric summary")
    return NumericSummary(
        count=_integer(mapping.get("count"), "count"),
        missing_count=_integer(mapping.get("missing_count"), "missing_count"),
        finite_count=_integer(mapping.get("finite_count"), "finite_count"),
        minimum=_optional_float(mapping.get("minimum"), "minimum"),
        maximum=_optional_float(mapping.get("maximum"), "maximum"),
        mean=_optional_float(mapping.get("mean"), "mean"),
        standard_deviation=_optional_float(
            mapping.get("standard_deviation"),
            "standard_deviation",
        ),
        quantiles=_string_float_mapping(mapping.get("quantiles"), "quantiles"),
    )


def numeric_reference_profile_payload(
    profile: NumericReferenceProfile,
) -> dict[str, object]:
    """Serialize fixed numeric bins and safe statistics."""
    return {
        "summary": numeric_summary_payload(profile.summary),
        "bin_edges": list(profile.bin_edges),
        "bin_counts": list(profile.bin_counts),
    }


def parse_numeric_reference_profile(payload: object) -> NumericReferenceProfile:
    """Parse fixed numeric bins and safe statistics."""
    mapping = _string_mapping(payload, "numeric reference profile")
    return NumericReferenceProfile(
        summary=parse_numeric_summary(mapping.get("summary")),
        bin_edges=_float_tuple(mapping.get("bin_edges"), "bin_edges"),
        bin_counts=_integer_tuple(mapping.get("bin_counts"), "bin_counts"),
    )


def _string_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise MonitoringDataError(f"Persisted {name} is not an object.")
    return value


def _object_sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise MonitoringDataError(f"Persisted {name} is not an array.")
    return value


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise MonitoringDataError(f"Persisted {name} is not an integer.")
    return value


def _optional_float(value: object, name: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise MonitoringDataError(f"Persisted {name} is not numeric.")
    return float(value)


def _integer_tuple(value: object, name: str) -> tuple[int, ...]:
    return tuple(_integer(item, name) for item in _object_sequence(value, name))


def _float_tuple(value: object, name: str) -> tuple[float, ...]:
    return tuple(_required_float(item, name) for item in _object_sequence(value, name))


def _required_float(value: object, name: str) -> float:
    parsed = _optional_float(value, name)
    if parsed is None:
        raise MonitoringDataError(f"Persisted {name} cannot be null.")
    return parsed


def _string_integer_mapping(value: object, name: str) -> dict[str, int]:
    mapping = _string_mapping(value, name)
    return {key: _integer(item, name) for key, item in mapping.items()}


def _string_float_mapping(value: object, name: str) -> dict[str, float]:
    mapping = _string_mapping(value, name)
    return {key: _required_float(item, name) for key, item in mapping.items()}
