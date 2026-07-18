"""Pure fixed-profile feature and prediction drift calculation."""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime

from app.ml.monitoring.models import (
    ClassificationPredictionDrift,
    ClassificationPredictionProfile,
    ClassificationPredictionReferenceProfile,
    DriftSeverity,
    DriftThresholds,
    FeatureDriftResult,
    ModelDriftReport,
    ModelReferenceProfile,
    NumericSummary,
    PredictionEvent,
    PredictionEventStatus,
    RegressionPredictionDrift,
    RegressionPredictionProfile,
    RegressionPredictionReferenceProfile,
)

_PARTIAL_WINDOW_WARNING = (
    "Drift was calculated from only the newest matching events within the "
    "configured analysis limit."
)


def population_stability_index(
    reference_counts: tuple[int, ...],
    current_counts: tuple[int, ...],
    *,
    epsilon: float,
) -> float:
    """Calculate PSI with per-bin epsilon smoothing and no raw observations."""
    if len(reference_counts) != len(current_counts) or not reference_counts:
        raise ValueError("PSI histograms must have equal non-zero lengths.")
    if any(count < 0 for count in (*reference_counts, *current_counts)):
        raise ValueError("PSI histogram counts must be non-negative.")
    reference_total = sum(reference_counts)
    current_total = sum(current_counts)
    if reference_total == 0 or current_total == 0:
        raise ValueError("PSI histograms must contain observations.")
    result = 0.0
    for reference_count, current_count in zip(
        reference_counts,
        current_counts,
        strict=True,
    ):
        reference_proportion = max(reference_count / reference_total, epsilon)
        current_proportion = max(current_count / current_total, epsilon)
        result += (current_proportion - reference_proportion) * math.log(
            current_proportion / reference_proportion,
        )
    return result


class DriftDetectionEngine:
    """Compare bounded event histograms with one exact-version reference."""

    def detect(
        self,
        *,
        reference: ModelReferenceProfile,
        events: tuple[PredictionEvent, ...],
        start_at: datetime,
        end_at: datetime,
        minimum_sample_count: int,
        thresholds: DriftThresholds,
        generated_at: datetime,
        matched_event_count: int,
    ) -> ModelDriftReport:
        """Return drift and disclose when newest-event input is partial."""
        analyzed_event_count = len(events)
        truncated = matched_event_count > analyzed_event_count
        successful = tuple(
            event
            for event in events
            if event.status is PredictionEventStatus.SUCCEEDED
            and event.resolved_model_version == reference.model_version
            and event.registered_model_name == reference.registered_model_name
        )
        current_sample_count = sum(event.row_count for event in successful)
        feature_results = tuple(
            self._feature_result(
                feature_index=index,
                reference=reference,
                events=successful,
                minimum_sample_count=minimum_sample_count,
                thresholds=thresholds,
            )
            for index in range(reference.feature_count)
        )
        prediction_result = self._prediction_result(
            reference=reference,
            events=successful,
            minimum_sample_count=minimum_sample_count,
            thresholds=thresholds,
        )
        severities = (
            *(result.severity for result in feature_results),
            prediction_result.severity,
        )
        aggregate_status = _aggregate_severity(severities)
        if current_sample_count < minimum_sample_count:
            aggregate_status = DriftSeverity.INSUFFICIENT_DATA
        return ModelDriftReport(
            registered_model_name=reference.registered_model_name,
            model_version=reference.model_version,
            key=reference.key,
            reference_source=reference.source,
            reference_sample_count=reference.sample_count,
            current_sample_count=current_sample_count,
            start_at=start_at,
            end_at=end_at,
            feature_results=feature_results,
            prediction_result=prediction_result,
            aggregate_status=aggregate_status,
            thresholds=thresholds,
            generated_at=generated_at,
            matched_event_count=matched_event_count,
            analyzed_event_count=analyzed_event_count,
            truncated=truncated,
            analysis_warning=_PARTIAL_WINDOW_WARNING if truncated else None,
        )

    def _feature_result(
        self,
        *,
        feature_index: int,
        reference: ModelReferenceProfile,
        events: tuple[PredictionEvent, ...],
        minimum_sample_count: int,
        thresholds: DriftThresholds,
    ) -> FeatureDriftResult:
        reference_feature = reference.features[feature_index].profile
        current_counts = [0] * len(reference_feature.bin_counts)
        current_count = 0
        current_missing = 0
        current_total = 0
        out_of_range = 0
        usable = True
        for event in events:
            if feature_index >= len(event.feature_profile):
                usable = False
                continue
            feature = event.feature_profile[feature_index]
            current_total += feature.summary.count
            current_missing += feature.summary.missing_count
            out_of_range += feature.out_of_reference_range_count
            bins = feature.reference_bin_counts
            if bins is None or len(bins) != len(current_counts):
                usable = False
                continue
            current_count += feature.summary.finite_count
            for index, count in enumerate(bins):
                current_counts[index] += count
        reference_total = reference_feature.summary.count
        reference_missing_rate = (
            reference_feature.summary.missing_count / reference_total
            if reference_total
            else 0.0
        )
        current_missing_rate = (
            current_missing / current_total if current_total else None
        )
        missing_difference = (
            current_missing_rate - reference_missing_rate
            if current_missing_rate is not None
            else None
        )
        out_of_range_proportion = (
            out_of_range / current_count if current_count else None
        )
        if not usable or current_count < minimum_sample_count:
            return FeatureDriftResult(
                feature_index=feature_index,
                psi=None,
                reference_sample_count=reference_feature.summary.finite_count,
                current_sample_count=current_count,
                missing_rate_difference=missing_difference,
                out_of_reference_range_proportion=out_of_range_proportion,
                severity=DriftSeverity.INSUFFICIENT_DATA,
            )
        psi = population_stability_index(
            reference_feature.bin_counts,
            tuple(current_counts),
            epsilon=thresholds.epsilon,
        )
        severity = _severity(psi, thresholds)
        if missing_difference is not None and abs(missing_difference) >= (
            thresholds.missing_rate_warning
        ):
            severity = max_severity(severity, DriftSeverity.WARNING)
        if out_of_range_proportion is not None and out_of_range_proportion >= (
            thresholds.out_of_range_warning
        ):
            severity = max_severity(severity, DriftSeverity.WARNING)
        return FeatureDriftResult(
            feature_index=feature_index,
            psi=psi,
            reference_sample_count=reference_feature.summary.finite_count,
            current_sample_count=current_count,
            missing_rate_difference=missing_difference,
            out_of_reference_range_proportion=out_of_range_proportion,
            severity=severity,
        )

    def _prediction_result(
        self,
        *,
        reference: ModelReferenceProfile,
        events: tuple[PredictionEvent, ...],
        minimum_sample_count: int,
        thresholds: DriftThresholds,
    ) -> RegressionPredictionDrift | ClassificationPredictionDrift:
        if isinstance(
            reference.prediction,
            RegressionPredictionReferenceProfile,
        ):
            return self._regression_prediction_result(
                reference.prediction,
                events,
                minimum_sample_count,
                thresholds,
            )
        return self._classification_prediction_result(
            reference.prediction,
            events,
            minimum_sample_count,
            thresholds,
        )

    def _regression_prediction_result(
        self,
        reference: RegressionPredictionReferenceProfile,
        events: tuple[PredictionEvent, ...],
        minimum_sample_count: int,
        thresholds: DriftThresholds,
    ) -> RegressionPredictionDrift:
        current_bins = [0] * len(reference.profile.bin_counts)
        summaries: list[NumericSummary] = []
        usable = True
        for event in events:
            prediction = event.prediction_profile
            if not isinstance(prediction, RegressionPredictionProfile):
                usable = False
                continue
            summaries.append(prediction.summary)
            if prediction.reference_bin_counts is None or len(
                prediction.reference_bin_counts,
            ) != len(current_bins):
                usable = False
                continue
            for index, count in enumerate(prediction.reference_bin_counts):
                current_bins[index] += count
        current_summary = _combine_numeric_summaries(summaries)
        current_count = current_summary.finite_count
        if not usable or current_count < minimum_sample_count:
            return RegressionPredictionDrift(
                psi=None,
                mean_shift=None,
                standard_deviation_ratio=None,
                reference_sample_count=reference.profile.summary.finite_count,
                current_sample_count=current_count,
                severity=DriftSeverity.INSUFFICIENT_DATA,
            )
        psi = population_stability_index(
            reference.profile.bin_counts,
            tuple(current_bins),
            epsilon=thresholds.epsilon,
        )
        reference_mean = reference.profile.summary.mean
        current_mean = current_summary.mean
        reference_std = reference.profile.summary.standard_deviation
        current_std = current_summary.standard_deviation
        mean_shift = (
            current_mean - reference_mean
            if current_mean is not None and reference_mean is not None
            else None
        )
        standard_deviation_ratio = (
            current_std / reference_std
            if current_std is not None
            and reference_std is not None
            and reference_std > 0
            else (1.0 if current_std == reference_std == 0 else None)
        )
        return RegressionPredictionDrift(
            psi=psi,
            mean_shift=mean_shift,
            standard_deviation_ratio=standard_deviation_ratio,
            reference_sample_count=reference.profile.summary.finite_count,
            current_sample_count=current_count,
            severity=_severity(psi, thresholds),
        )

    def _classification_prediction_result(
        self,
        reference: ClassificationPredictionReferenceProfile,
        events: tuple[PredictionEvent, ...],
        minimum_sample_count: int,
        thresholds: DriftThresholds,
    ) -> ClassificationPredictionDrift:
        current: Counter[str] = Counter()
        current_other = 0
        current_count = 0
        usable = True
        for event in events:
            prediction = event.prediction_profile
            if not isinstance(prediction, ClassificationPredictionProfile):
                usable = False
                continue
            current.update(prediction.class_counts)
            current_other += prediction.other_count
            current_count += prediction.count
        if not usable or current_count < minimum_sample_count:
            return ClassificationPredictionDrift(
                total_variation_distance=None,
                reference_sample_count=reference.profile.count,
                current_sample_count=current_count,
                severity=DriftSeverity.INSUFFICIENT_DATA,
            )
        labels = set(reference.profile.class_counts) | set(current)
        reference_total = reference.profile.count
        total_variation = 0.5 * (
            sum(
                abs(
                    reference.profile.class_counts.get(label, 0) / reference_total
                    - current.get(label, 0) / current_count,
                )
                for label in labels
            )
            + abs(
                reference.profile.other_count / reference_total
                - current_other / current_count,
            )
        )
        return ClassificationPredictionDrift(
            total_variation_distance=total_variation,
            reference_sample_count=reference.profile.count,
            current_sample_count=current_count,
            severity=_severity(total_variation, thresholds),
        )


def _combine_numeric_summaries(summaries: list[NumericSummary]) -> NumericSummary:
    count = sum(summary.count for summary in summaries)
    missing = sum(summary.missing_count for summary in summaries)
    finite = sum(summary.finite_count for summary in summaries)
    if finite == 0:
        return NumericSummary(count, missing, 0, None, None, None, None, {})
    means = tuple(
        (summary.finite_count, summary.mean, summary.standard_deviation)
        for summary in summaries
        if summary.finite_count > 0
        and summary.mean is not None
        and summary.standard_deviation is not None
    )
    mean = sum(item_count * item_mean for item_count, item_mean, _ in means) / finite
    second_moment = (
        sum(
            item_count * (item_std**2 + item_mean**2)
            for item_count, item_mean, item_std in means
        )
        / finite
    )
    variance = max(second_moment - mean**2, 0.0)
    minima = tuple(
        summary.minimum for summary in summaries if summary.minimum is not None
    )
    maxima = tuple(
        summary.maximum for summary in summaries if summary.maximum is not None
    )
    return NumericSummary(
        count=count,
        missing_count=missing,
        finite_count=finite,
        minimum=min(minima),
        maximum=max(maxima),
        mean=mean,
        standard_deviation=math.sqrt(variance),
        quantiles={},
    )


def _severity(value: float, thresholds: DriftThresholds) -> DriftSeverity:
    if value >= thresholds.critical:
        return DriftSeverity.CRITICAL
    if value >= thresholds.warning:
        return DriftSeverity.WARNING
    return DriftSeverity.STABLE


def max_severity(first: DriftSeverity, second: DriftSeverity) -> DriftSeverity:
    """Return the higher actionable severity without hiding insufficient data."""
    order = {
        DriftSeverity.INSUFFICIENT_DATA: 0,
        DriftSeverity.STABLE: 1,
        DriftSeverity.WARNING: 2,
        DriftSeverity.CRITICAL: 3,
    }
    return first if order[first] >= order[second] else second


def _aggregate_severity(severities: tuple[DriftSeverity, ...]) -> DriftSeverity:
    if DriftSeverity.CRITICAL in severities:
        return DriftSeverity.CRITICAL
    if DriftSeverity.WARNING in severities:
        return DriftSeverity.WARNING
    if DriftSeverity.INSUFFICIENT_DATA in severities:
        return DriftSeverity.INSUFFICIENT_DATA
    return DriftSeverity.STABLE
