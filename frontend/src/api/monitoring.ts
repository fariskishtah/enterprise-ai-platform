import { apiRequest } from "./client";
import type { TrainingTask } from "./aiLifecycle";

export type MonitoringStatus =
  "critical" | "healthy" | "insufficient_data" | "unavailable" | "warning";
export type DriftStatus = "critical" | "insufficient_data" | "stable" | "warning";

export interface MonitoringEvaluation {
  readonly id: string;
  readonly registered_model_name: string;
  readonly model_version: string;
  readonly model_alias: string | null;
  readonly algorithm: string;
  readonly task_type: TrainingTask;
  readonly window_start: string;
  readonly window_end: string;
  readonly evaluated_sample_count: number;
  readonly successful_prediction_count: number;
  readonly failed_prediction_count: number;
  readonly data_quality_status: MonitoringStatus;
  readonly feature_drift_status: MonitoringStatus;
  readonly prediction_drift_status: MonitoringStatus;
  readonly operational_health_status: MonitoringStatus;
  readonly overall_status: MonitoringStatus;
  readonly report_schema_version: string;
  readonly report: Readonly<Record<string, unknown>>;
  readonly warning_count: number;
  readonly critical_count: number;
  readonly trigger: "manual" | "reconciliation" | "scheduled";
  readonly created_at: string;
  readonly updated_at: string;
}

export interface EvaluationPage {
  readonly items: readonly MonitoringEvaluation[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}
export interface OperationsSummary {
  readonly registered_model_name: string;
  readonly model_version: string;
  readonly start_at: string;
  readonly end_at: string;
  readonly request_count: number;
  readonly success_count: number;
  readonly failure_count: number;
  readonly success_rate: number;
  readonly failure_rate: number;
  readonly average_latency_ms: number | null;
  readonly p50_latency_ms: number | null;
  readonly p95_latency_ms: number | null;
  readonly p99_latency_ms: number | null;
  readonly total_predicted_rows: number;
  readonly average_batch_size: number | null;
  readonly failures_by_error_code: Readonly<Record<string, number>>;
  readonly truncated: boolean;
  readonly analysis_warning: string | null;
}
export interface DataQualitySummary {
  readonly registered_model_name: string;
  readonly model_version: string;
  readonly request_count: number;
  readonly row_count: number;
  readonly missing_value_count: number;
  readonly non_finite_value_count: number;
  readonly feature_count_mismatch_requests: number;
  readonly empty_batch_requests: number;
  readonly constant_column_occurrences: number;
  readonly out_of_reference_range_count: number;
  readonly out_of_reference_range_proportion: number;
  readonly issues: readonly {
    readonly code: string;
    readonly severity: "critical" | "warning";
    readonly count: number;
    readonly proportion: number;
  }[];
  readonly truncated: boolean;
  readonly analysis_warning: string | null;
}
export interface DriftReport {
  readonly registered_model_name: string;
  readonly model_version: string;
  readonly reference_sample_count: number;
  readonly current_sample_count: number;
  readonly aggregate_status: DriftStatus;
  readonly feature_results: readonly {
    readonly feature_index: number;
    readonly psi: number | null;
    readonly severity: DriftStatus;
  }[];
  readonly prediction_result: Readonly<Record<string, unknown>>;
  readonly generated_at: string;
  readonly truncated: boolean;
  readonly analysis_warning: string | null;
}
export interface ReferenceProfile {
  readonly profile_id: string;
  readonly registered_model_name: string;
  readonly model_version: string;
  readonly source: "evaluation";
  readonly feature_count: number;
  readonly sample_count: number;
  readonly training_job_id: string;
  readonly created_at: string;
  readonly features: readonly unknown[];
  readonly prediction: unknown;
}
export type PerformanceSummary =
  | {
      readonly registered_model_name: string;
      readonly model_version: string;
      readonly evaluated_sample_count: number;
      readonly task_type: "regression";
      readonly mae: number;
      readonly rmse: number;
      readonly mean_prediction_bias: number;
    }
  | {
      readonly registered_model_name: string;
      readonly model_version: string;
      readonly evaluated_sample_count: number;
      readonly task_type: "classification";
      readonly accuracy: number;
      readonly precision: number;
      readonly recall: number;
      readonly f1: number;
      readonly false_negative_rate: number;
      readonly true_positive_count: number;
      readonly true_negative_count: number;
      readonly false_positive_count: number;
      readonly false_negative_count: number;
    };

const modelPath = (name: string, version: string): string =>
  `/ai/monitoring/models/${encodeURIComponent(name)}/versions/${encodeURIComponent(version)}`;
const pageQuery = (options: {
  limit: number;
  offset: number;
  modelName?: string;
  version?: string;
  status?: MonitoringStatus;
}): string => {
  const q = new URLSearchParams({
    limit: String(options.limit),
    offset: String(options.offset),
  });
  if (options.modelName) q.set("registered_model_name", options.modelName);
  if (options.version) q.set("model_version", options.version);
  if (options.status) q.set("overall_status", options.status);
  return q.toString();
};

export const listEvaluations = (options: {
  limit: number;
  offset: number;
  modelName?: string;
  version?: string;
  status?: MonitoringStatus;
  signal?: AbortSignal;
}): Promise<EvaluationPage> =>
  apiRequest(`/ai/monitoring/evaluations?${pageQuery(options)}`, {
    signal: options.signal,
  });
export const getEvaluation = (
  id: string,
  signal?: AbortSignal,
): Promise<MonitoringEvaluation> =>
  apiRequest(`/ai/monitoring/evaluations/${encodeURIComponent(id)}`, { signal });
export const getEvaluationHistory = (
  name: string,
  version: string,
  signal?: AbortSignal,
): Promise<EvaluationPage> =>
  apiRequest(`${modelPath(name, version)}/evaluations?limit=50&offset=0`, { signal });
export const triggerEvaluation = (
  name: string,
  version: string,
  payload: { window_start: string | null; window_end: string | null },
): Promise<MonitoringEvaluation> =>
  apiRequest(`${modelPath(name, version)}/evaluations`, {
    body: JSON.stringify(payload),
    method: "POST",
  });
export const getLatestEvaluation = (
  name: string,
  version: string,
  signal?: AbortSignal,
): Promise<MonitoringEvaluation> =>
  apiRequest(`${modelPath(name, version)}/status/latest`, { signal });
export const getOperations = (
  name: string,
  version: string,
  signal?: AbortSignal,
): Promise<OperationsSummary> =>
  apiRequest(`${modelPath(name, version)}/operations`, { signal });
export const getDataQuality = (
  name: string,
  version: string,
  signal?: AbortSignal,
): Promise<DataQualitySummary> =>
  apiRequest(`${modelPath(name, version)}/data-quality`, { signal });
export const getDrift = (
  name: string,
  version: string,
  signal?: AbortSignal,
): Promise<DriftReport> => apiRequest(`${modelPath(name, version)}/drift`, { signal });
export const getReferenceProfile = (
  name: string,
  version: string,
  signal?: AbortSignal,
): Promise<ReferenceProfile> =>
  apiRequest(`${modelPath(name, version)}/reference-profile`, { signal });
export const getPerformance = (
  name: string,
  version: string,
  signal?: AbortSignal,
): Promise<PerformanceSummary> =>
  apiRequest(`${modelPath(name, version)}/performance`, { signal });
