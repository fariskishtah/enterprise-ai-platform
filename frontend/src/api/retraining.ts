import { apiRequest } from "./client";

export type RetrainingTrigger =
  "data_quality" | "feature_drift" | "manual" | "prediction_drift";
export type RetrainingDecisionStatus =
  | "blocked_cooldown"
  | "blocked_duplicate"
  | "blocked_insufficient_data"
  | "blocked_missing_profile"
  | "blocked_missing_training_evidence"
  | "blocked_quota"
  | "disabled"
  | "eligible"
  | "not_eligible";
export type RetrainingRequestStatus =
  | "cancelled"
  | "candidate_created"
  | "completed"
  | "failed"
  | "pending"
  | "submitted"
  | "training";
export type ComparisonStatus = "better" | "mixed" | "not_comparable" | "worse";
export interface RetrainingStatus {
  readonly total_requests: number;
  readonly active_requests: number;
  readonly completed_requests: number;
  readonly failed_requests: number;
}
export interface RetrainingPolicy {
  readonly id: string;
  readonly registered_model_name: string;
  readonly enabled: boolean;
  readonly allowed_trigger_types: readonly RetrainingTrigger[];
  readonly minimum_drift_status: "critical" | "warning";
  readonly minimum_current_sample_count: number;
  readonly cooldown_seconds: number;
  readonly maximum_requests_per_day: number;
  readonly maximum_requests_per_week: number;
  readonly maximum_active_requests: number;
  readonly require_champion_source: boolean;
  readonly allow_truncated_drift: boolean;
  readonly created_by_user_id: string;
  readonly created_at: string;
  readonly updated_at: string;
}
export interface RetrainingDecision {
  readonly registered_model_name: string;
  readonly source_model_version: string | null;
  readonly requested_alias: string | null;
  readonly trigger_type: RetrainingTrigger;
  readonly trigger_reference: string;
  readonly aggregate_status: string | null;
  readonly matched_event_count: number;
  readonly analyzed_event_count: number;
  readonly current_sample_count: number;
  readonly truncated: boolean;
  readonly analysis_warning: string | null;
  readonly thresholds: Readonly<Record<string, number>>;
  readonly decision_status: RetrainingDecisionStatus;
  readonly reasons: readonly string[];
  readonly evaluated_at: string;
  readonly cooldown: {
    readonly active: boolean;
    readonly started_at: string | null;
    readonly expires_at: string | null;
    readonly remaining_seconds: number;
  };
  readonly quota: {
    readonly requests_today: number;
    readonly requests_this_week: number;
    readonly active_requests: number;
    readonly maximum_per_day: number;
    readonly maximum_per_week: number;
    readonly maximum_active: number;
  };
  readonly existing_request_id: string | null;
}
export interface MetricComparison {
  readonly metric: string;
  readonly source_value: number;
  readonly candidate_value: number;
  readonly higher_is_better: boolean;
  readonly outcome: ComparisonStatus;
}
export interface CandidateComparison {
  readonly status: ComparisonStatus;
  readonly metrics: readonly MetricComparison[];
  readonly source_model_version: string;
  readonly candidate_model_version: string;
  readonly compared_at: string;
}
export interface RetrainingRequest {
  readonly id: string;
  readonly registered_model_name: string;
  readonly source_model_version: string;
  readonly source_training_job_id: string;
  readonly algorithm: string;
  readonly task_type: "classification" | "regression";
  readonly trigger_type: RetrainingTrigger;
  readonly trigger_reference: string;
  readonly policy_id: string;
  readonly decision_status: RetrainingDecisionStatus;
  readonly request_status: RetrainingRequestStatus;
  readonly evaluation_mode: "automatic" | "manual";
  readonly training_job_id: string | null;
  readonly monitoring_evaluation_id: string | null;
  readonly resulting_model_version: string | null;
  readonly requested_by_user_id: string;
  readonly reason: string | null;
  readonly override_used: boolean;
  readonly requested_at: string;
  readonly started_at: string | null;
  readonly completed_at: string | null;
  readonly safe_failure_code: string | null;
  readonly safe_failure_message: string | null;
  readonly comparison: CandidateComparison | null;
  readonly created_at: string;
  readonly updated_at: string;
}
export interface RetrainingEvaluation {
  readonly decision: RetrainingDecision;
  readonly request: RetrainingRequest | null;
}
export interface RetrainingRequestPage {
  readonly items: readonly RetrainingRequest[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}
export interface RetrainingAuditPage {
  readonly items: readonly {
    readonly id: string;
    readonly decision: RetrainingDecision;
    readonly evaluated_by_user_id: string;
    readonly evaluation_mode: "automatic" | "manual";
    readonly override_used: boolean;
    readonly override_reason: string | null;
    readonly created_request_id: string | null;
  }[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

const modelPath = (name: string, version: string): string =>
  `/ai/retraining/models/${encodeURIComponent(name)}/versions/${encodeURIComponent(version)}`;
export const getRetrainingStatus = (signal?: AbortSignal): Promise<RetrainingStatus> =>
  apiRequest("/ai/retraining/status", { signal });
export const listPolicies = (
  signal?: AbortSignal,
): Promise<readonly RetrainingPolicy[]> =>
  apiRequest("/ai/retraining/policies?limit=50&offset=0", { signal });
export const updatePolicy = (
  name: string,
  payload: Omit<
    RetrainingPolicy,
    "created_at" | "created_by_user_id" | "id" | "registered_model_name" | "updated_at"
  >,
): Promise<RetrainingPolicy> =>
  apiRequest(`/ai/retraining/policies/${encodeURIComponent(name)}`, {
    body: JSON.stringify(payload),
    method: "PUT",
  });
export const evaluateRetraining = (
  name: string,
  version: string,
  payload: {
    readonly trigger_type: RetrainingTrigger;
    readonly start_at: string | null;
    readonly end_at: string | null;
    readonly minimum_sample_count: number | null;
    readonly submit_if_eligible: boolean;
  },
): Promise<RetrainingEvaluation> =>
  apiRequest(`${modelPath(name, version)}/evaluate`, {
    body: JSON.stringify(payload),
    method: "POST",
  });
export const requestRetraining = (
  name: string,
  version: string,
  payload: { readonly reason: string; readonly override_cooldown: boolean },
): Promise<RetrainingEvaluation> =>
  apiRequest(`${modelPath(name, version)}/requests`, {
    body: JSON.stringify(payload),
    method: "POST",
  });
export function listRetrainingRequests(options: {
  readonly limit: number;
  readonly modelName?: string;
  readonly offset: number;
  readonly signal?: AbortSignal;
}): Promise<RetrainingRequestPage> {
  const q = new URLSearchParams({
    limit: String(options.limit),
    offset: String(options.offset),
  });
  if (options.modelName) q.set("registered_model_name", options.modelName);
  return apiRequest(`/ai/retraining/requests?${q.toString()}`, {
    signal: options.signal,
  });
}
export const getRetrainingRequest = (
  id: string,
  signal?: AbortSignal,
): Promise<RetrainingRequest> =>
  apiRequest(`/ai/retraining/requests/${encodeURIComponent(id)}`, { signal });
export const getRetrainingComparison = (
  id: string,
  signal?: AbortSignal,
): Promise<CandidateComparison> =>
  apiRequest(`/ai/retraining/requests/${encodeURIComponent(id)}/comparison`, {
    signal,
  });
export const listRetrainingAudits = (
  signal?: AbortSignal,
): Promise<RetrainingAuditPage> =>
  apiRequest("/ai/retraining/audits?limit=50&offset=0", { signal });
