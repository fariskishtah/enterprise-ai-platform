"""Pure fixed-bin feature and prediction drift tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import numpy as np
from app.ml.base import TrainerKey
from app.ml.domain import AlgorithmType, TaskType
from app.ml.monitoring import (
    ClassificationPredictionDrift,
    DriftDetectionEngine,
    DriftSeverity,
    DriftThresholds,
    ModelReferenceProfile,
    PredictionEvent,
    PredictionEventStatus,
    RegressionPredictionDrift,
    build_model_reference_profile,
    feature_request_profiles,
    population_stability_index,
    prediction_request_profile,
)
from app.ml.trainers.random_forest.types import (
    ClassificationPredictionArray,
    FeatureArray,
    RegressionPredictionArray,
)

NOW = datetime(2026, 7, 18, 12, tzinfo=UTC)
THRESHOLDS = DriftThresholds(
    warning=0.10,
    critical=0.25,
    missing_rate_warning=0.05,
    out_of_range_warning=0.10,
)


def _reference(*, classification: bool = False) -> ModelReferenceProfile:
    key = TrainerKey(
        AlgorithmType.RANDOM_FOREST,
        TaskType.CLASSIFICATION if classification else TaskType.REGRESSION,
    )
    features: FeatureArray = np.arange(20, dtype=np.float64).reshape(20, 1)
    predictions: RegressionPredictionArray | ClassificationPredictionArray
    if classification:
        predictions = np.asarray([0] * 10 + [1] * 10, dtype=np.int64)
    else:
        predictions = np.arange(20, dtype=np.float64)
    return build_model_reference_profile(
        profile_id=uuid4(),
        training_job_id=uuid4(),
        registered_model_name=(
            "ai_core_random_forest_classification"
            if classification
            else "ai_core_random_forest_regression"
        ),
        model_version="1",
        key=key,
        evaluation_features=features,
        predictions=predictions,
        bin_count=10,
        created_at=NOW,
    )


def _event(
    reference: ModelReferenceProfile,
    features: FeatureArray,
    predictions: RegressionPredictionArray | ClassificationPredictionArray,
) -> PredictionEvent:
    return PredictionEvent(
        id=uuid4(),
        requested_by_user_id=uuid4(),
        registered_model_name=reference.registered_model_name,
        requested_model_reference="1",
        resolved_model_version="1",
        resolved_aliases=(),
        key=reference.key,
        status=PredictionEventStatus.SUCCEEDED,
        row_count=features.shape[0],
        feature_count=features.shape[1],
        duration_ms=2.0,
        feature_profile=feature_request_profiles(features, reference),
        prediction_profile=prediction_request_profile(
            predictions,
            key=reference.key,
            reference=reference,
        ),
        error_code=None,
        safe_error_message=None,
        correlation_id=None,
        created_at=NOW,
        completed_at=NOW + timedelta(milliseconds=2),
    )


def test_identical_regression_distributions_are_stable() -> None:
    """Reference-shaped feature and output histograms have zero PSI."""
    reference = _reference()
    values: FeatureArray = np.arange(20, dtype=np.float64).reshape(20, 1)
    predictions: RegressionPredictionArray = np.arange(20, dtype=np.float64)

    report = DriftDetectionEngine().detect(
        reference=reference,
        events=(_event(reference, values, predictions),),
        start_at=NOW - timedelta(hours=1),
        end_at=NOW + timedelta(hours=1),
        minimum_sample_count=10,
        thresholds=THRESHOLDS,
        generated_at=NOW,
        matched_event_count=1,
    )

    assert report.aggregate_status is DriftSeverity.STABLE
    assert report.feature_results[0].psi == 0.0
    assert isinstance(report.prediction_result, RegressionPredictionDrift)
    assert report.prediction_result.psi == 0.0
    assert report.prediction_result.mean_shift == 0.0


def test_shifted_regression_distributions_are_critical() -> None:
    """Fixed reference edges expose a large feature and prediction shift."""
    reference = _reference()
    values: FeatureArray = np.arange(100, 120, dtype=np.float64).reshape(20, 1)
    predictions: RegressionPredictionArray = np.arange(200, 220, dtype=np.float64)

    report = DriftDetectionEngine().detect(
        reference=reference,
        events=(_event(reference, values, predictions),),
        start_at=NOW - timedelta(hours=1),
        end_at=NOW + timedelta(hours=1),
        minimum_sample_count=10,
        thresholds=THRESHOLDS,
        generated_at=NOW,
        matched_event_count=1,
    )

    assert report.aggregate_status is DriftSeverity.CRITICAL
    assert report.feature_results[0].severity is DriftSeverity.CRITICAL
    assert report.feature_results[0].out_of_reference_range_proportion == 1.0


def test_classification_drift_uses_label_frequency_and_detects_unseen_label() -> None:
    """Classification compares predicted labels, not unavailable probabilities."""
    reference = _reference(classification=True)
    features: FeatureArray = np.arange(20, dtype=np.float64).reshape(20, 1)
    predictions: ClassificationPredictionArray = np.full(20, 2, dtype=np.int64)

    report = DriftDetectionEngine().detect(
        reference=reference,
        events=(_event(reference, features, predictions),),
        start_at=NOW - timedelta(hours=1),
        end_at=NOW + timedelta(hours=1),
        minimum_sample_count=10,
        thresholds=THRESHOLDS,
        generated_at=NOW,
        matched_event_count=1,
    )

    assert isinstance(report.prediction_result, ClassificationPredictionDrift)
    assert report.prediction_result.total_variation_distance == 1.0
    assert report.prediction_result.severity is DriftSeverity.CRITICAL


def test_insufficient_samples_and_zero_bins_are_explicit() -> None:
    """Small windows do not produce misleading actionable drift status."""
    reference = _reference()
    features: FeatureArray = np.asarray([[1.0]], dtype=np.float64)
    predictions: RegressionPredictionArray = np.asarray([1.0], dtype=np.float64)

    report = DriftDetectionEngine().detect(
        reference=reference,
        events=(_event(reference, features, predictions),),
        start_at=NOW - timedelta(hours=1),
        end_at=NOW + timedelta(hours=1),
        minimum_sample_count=2,
        thresholds=THRESHOLDS,
        generated_at=NOW,
        matched_event_count=1,
    )

    assert report.aggregate_status is DriftSeverity.INSUFFICIENT_DATA
    assert report.feature_results[0].psi is None
    assert population_stability_index((10, 0), (10, 0), epsilon=1e-6) == 0.0
