"""Privacy-preserving request summaries and model reference profiles."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import numpy as np
import numpy.typing as npt

from app.ml.base import TrainerKey
from app.ml.domain import TaskType
from app.ml.monitoring.models import (
    MAX_PERSISTED_CLASS_LABELS,
    ClassificationPredictionProfile,
    ClassificationPredictionReferenceProfile,
    FeatureReferenceProfile,
    FeatureRequestProfile,
    ModelReferenceProfile,
    ModelReferenceProfileDraft,
    NumericReferenceProfile,
    NumericSummary,
    PredictionReferenceProfile,
    PredictionRequestProfile,
    ReferenceProfileSource,
    RegressionPredictionProfile,
    RegressionPredictionReferenceProfile,
)
from app.ml.trainers.random_forest.types import (
    ClassificationPredictionArray,
    FeatureArray,
    RegressionPredictionArray,
)

_SUMMARY_QUANTILES: tuple[tuple[str, float], ...] = (
    ("p00", 0.0),
    ("p25", 0.25),
    ("p50", 0.5),
    ("p75", 0.75),
    ("p100", 1.0),
)


def numeric_summary(values: npt.NDArray[np.float64]) -> NumericSummary:
    """Summarize a one-dimensional numeric vector without retaining its rows."""
    flattened = np.ravel(values)
    finite = flattened[np.isfinite(flattened)]
    missing_count = int(np.isnan(flattened).sum())
    if finite.size == 0:
        return NumericSummary(
            count=int(flattened.size),
            missing_count=missing_count,
            finite_count=0,
            minimum=None,
            maximum=None,
            mean=None,
            standard_deviation=None,
            quantiles={},
        )
    quantile_values = np.quantile(
        finite,
        [quantile for _, quantile in _SUMMARY_QUANTILES],
    )
    return NumericSummary(
        count=int(flattened.size),
        missing_count=missing_count,
        finite_count=int(finite.size),
        minimum=float(np.min(finite)),
        maximum=float(np.max(finite)),
        mean=float(np.mean(finite)),
        standard_deviation=float(np.std(finite)),
        quantiles={
            name: float(value)
            for (name, _), value in zip(
                _SUMMARY_QUANTILES,
                quantile_values,
                strict=True,
            )
        },
    )


def numeric_reference_profile(
    values: npt.NDArray[np.float64],
    *,
    bin_count: int,
) -> NumericReferenceProfile:
    """Create fixed quantile boundaries plus underflow and overflow bins."""
    if not 10 <= bin_count <= 20:
        raise ValueError("Reference profile bin_count must be between 10 and 20.")
    summary = numeric_summary(values)
    finite = np.ravel(values)[np.isfinite(np.ravel(values))]
    if finite.size == 0:
        raise ValueError("Reference profiles require at least one finite value.")
    quantiles = np.quantile(
        finite,
        [index / bin_count for index in range(1, bin_count)],
    )
    edges = tuple(float(value) for value in np.unique(quantiles))
    counts = _histogram_counts(finite, edges)
    return NumericReferenceProfile(
        summary=summary,
        bin_edges=edges,
        bin_counts=counts,
    )


def build_model_reference_profile(
    *,
    profile_id: UUID,
    training_job_id: UUID,
    registered_model_name: str,
    model_version: str,
    key: TrainerKey,
    evaluation_features: FeatureArray,
    predictions: RegressionPredictionArray | ClassificationPredictionArray,
    bin_count: int,
    created_at: datetime,
) -> ModelReferenceProfile:
    """Build one exact-version profile from held-out features and predictions."""
    return build_model_reference_profile_draft(
        registered_model_name=registered_model_name,
        model_version=model_version,
        key=key,
        evaluation_features=evaluation_features,
        predictions=predictions,
        bin_count=bin_count,
        created_at=created_at,
    ).finalize(profile_id=profile_id, training_job_id=training_job_id)


def build_model_reference_profile_draft(
    *,
    registered_model_name: str,
    model_version: str,
    key: TrainerKey,
    evaluation_features: FeatureArray,
    predictions: RegressionPredictionArray | ClassificationPredictionArray,
    bin_count: int,
    created_at: datetime,
) -> ModelReferenceProfileDraft:
    """Summarize held-out data before a worker attaches persistence IDs."""
    if evaluation_features.ndim != 2 or evaluation_features.shape[0] == 0:
        raise ValueError("Evaluation features must be a non-empty matrix.")
    features = tuple(
        FeatureReferenceProfile(
            feature_index=index,
            profile=numeric_reference_profile(
                evaluation_features[:, index],
                bin_count=bin_count,
            ),
        )
        for index in range(evaluation_features.shape[1])
    )
    prediction: PredictionReferenceProfile
    if key.task_type is TaskType.REGRESSION:
        regression_predictions: RegressionPredictionArray = np.asarray(
            predictions,
            dtype=np.float64,
        )
        prediction = RegressionPredictionReferenceProfile(
            numeric_reference_profile(
                regression_predictions,
                bin_count=bin_count,
            ),
        )
    else:
        classification_predictions: ClassificationPredictionArray = np.asarray(
            predictions,
            dtype=np.int64,
        )
        prediction = ClassificationPredictionReferenceProfile(
            classification_prediction_profile(classification_predictions),
        )
    return ModelReferenceProfileDraft(
        registered_model_name=registered_model_name,
        model_version=model_version,
        key=key,
        source=ReferenceProfileSource.EVALUATION,
        feature_count=evaluation_features.shape[1],
        features=features,
        prediction=prediction,
        sample_count=evaluation_features.shape[0],
        created_at=created_at,
    )


def feature_request_profiles(
    features: FeatureArray,
    reference: ModelReferenceProfile | None,
) -> tuple[FeatureRequestProfile, ...]:
    """Summarize features and, when available, count fixed reference bins."""
    if features.ndim != 2:
        return ()
    profiles: list[FeatureRequestProfile] = []
    for index in range(features.shape[1]):
        values = features[:, index]
        summary = numeric_summary(values)
        reference_feature = (
            reference.features[index]
            if reference is not None and index < reference.feature_count
            else None
        )
        bin_counts: tuple[int, ...] | None = None
        out_of_range_count = 0
        if reference_feature is not None:
            finite = values[np.isfinite(values)]
            bin_counts = _histogram_counts(
                finite,
                reference_feature.profile.bin_edges,
            )
            minimum = reference_feature.profile.summary.minimum
            maximum = reference_feature.profile.summary.maximum
            if minimum is not None and maximum is not None:
                out_of_range_count = int(
                    np.count_nonzero((finite < minimum) | (finite > maximum)),
                )
        profiles.append(
            FeatureRequestProfile(
                feature_index=index,
                summary=summary,
                reference_bin_counts=bin_counts,
                out_of_reference_range_count=out_of_range_count,
            ),
        )
    return tuple(profiles)


def regression_prediction_profile(
    predictions: RegressionPredictionArray,
    reference: ModelReferenceProfile | None,
) -> RegressionPredictionProfile:
    """Summarize scalar predictions against their version-owned fixed bins."""
    summary = numeric_summary(predictions)
    bin_counts: tuple[int, ...] | None = None
    if reference is not None and isinstance(
        reference.prediction,
        RegressionPredictionReferenceProfile,
    ):
        finite = predictions[np.isfinite(predictions)]
        bin_counts = _histogram_counts(
            finite,
            reference.prediction.profile.bin_edges,
        )
    return RegressionPredictionProfile(summary, bin_counts)


def classification_prediction_profile(
    predictions: ClassificationPredictionArray,
) -> ClassificationPredictionProfile:
    """Persist only a deterministic, capped predicted-label frequency mapping."""
    labels, counts = np.unique(predictions, return_counts=True)
    ranked = sorted(
        ((int(label), int(count)) for label, count in zip(labels, counts, strict=True)),
        key=lambda item: (-item[1], item[0]),
    )
    retained = ranked[:MAX_PERSISTED_CLASS_LABELS]
    return ClassificationPredictionProfile(
        count=int(predictions.size),
        class_counts={f"label:{label}": count for label, count in retained},
        other_count=sum(count for _, count in ranked[MAX_PERSISTED_CLASS_LABELS:]),
    )


def prediction_request_profile(
    predictions: RegressionPredictionArray | ClassificationPredictionArray,
    *,
    key: TrainerKey,
    reference: ModelReferenceProfile | None,
) -> PredictionRequestProfile:
    """Dispatch task-specific prediction summaries using the protected key."""
    if key.task_type is TaskType.REGRESSION:
        regression: RegressionPredictionArray = np.asarray(
            predictions, dtype=np.float64
        )
        return regression_prediction_profile(regression, reference)
    classification: ClassificationPredictionArray = np.asarray(
        predictions,
        dtype=np.int64,
    )
    return classification_prediction_profile(classification)


def _histogram_counts(
    finite_values: npt.NDArray[np.float64],
    edges: Sequence[float],
) -> tuple[int, ...]:
    boundaries = np.asarray([-np.inf, *edges, np.inf], dtype=np.float64)
    counts, _ = np.histogram(finite_values, bins=boundaries)
    return tuple(int(count) for count in counts)
