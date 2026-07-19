"""Prediction monitoring domain and privacy-boundary tests."""

from dataclasses import FrozenInstanceError, fields

import numpy as np
import pytest
from app.ml.monitoring import (
    MAX_PERSISTED_CLASS_LABELS,
    ClassificationPredictionProfile,
    NumericSummary,
    classification_prediction_profile,
    numeric_reference_profile,
    numeric_summary,
)
from app.ml.trainers.random_forest.types import ClassificationPredictionArray
from app.models.ai_monitoring import PredictionEventEntity


def test_numeric_summary_preserves_only_safe_aggregates() -> None:
    """NaN and infinity are counted but raw observations are not retained."""
    values = np.asarray([1.0, 2.0, np.nan, np.inf], dtype=np.float64)

    summary = numeric_summary(values)

    assert summary == NumericSummary(
        count=4,
        missing_count=1,
        finite_count=2,
        minimum=1.0,
        maximum=2.0,
        mean=1.5,
        standard_deviation=0.5,
        quantiles={
            "p00": 1.0,
            "p25": 1.25,
            "p50": 1.5,
            "p75": 1.75,
            "p100": 2.0,
        },
    )
    assert summary.non_finite_count == 2
    assert "values" not in {field.name for field in fields(summary)}


def test_classification_summary_caps_persisted_label_vocabulary() -> None:
    """Unbounded integer labels collapse into an explicit other count."""
    predictions: ClassificationPredictionArray = np.arange(
        MAX_PERSISTED_CLASS_LABELS + 7,
        dtype=np.int64,
    )

    profile = classification_prediction_profile(predictions)

    assert isinstance(profile, ClassificationPredictionProfile)
    assert len(profile.class_counts) == MAX_PERSISTED_CLASS_LABELS
    assert profile.other_count == 7
    assert sum(profile.class_counts.values()) + profile.other_count == profile.count


def test_reference_bins_are_deterministic_and_safe_for_constant_features() -> None:
    """Constant features produce fixed counts without division or edge failures."""
    values = np.full(25, 3.5, dtype=np.float64)

    first = numeric_reference_profile(values, bin_count=10)
    second = numeric_reference_profile(values, bin_count=10)

    assert first == second
    assert sum(first.bin_counts) == 25
    assert first.summary.standard_deviation == 0.0


def test_monitoring_records_are_immutable_and_orm_has_no_raw_matrix_column() -> None:
    """Domain summaries are frozen and persistence has no raw feature field."""
    summary = numeric_summary(np.asarray([1.0], dtype=np.float64))

    def mutate(value: object) -> None:
        attribute = "count"
        setattr(value, attribute, 2)

    with pytest.raises(FrozenInstanceError):
        mutate(summary)

    columns = set(PredictionEventEntity.__table__.columns.keys())
    assert "feature_profile" in columns
    assert "prediction_profile" in columns
    assert "features" not in columns
    assert "predictions" not in columns
    assert "raw_features" not in columns
    assert "raw_predictions" not in columns
