import { apiRequest } from "./client";

export type AutoMLTask = "classification" | "regression";
export type MetricDirection = "maximize" | "minimize";
export type AutoMLStudyStatus =
  "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type AutoMLTrialStatus = AutoMLStudyStatus | "pruned";
export type SearchScalar = boolean | number | string;

export interface AutoMLSearchParameter {
  readonly name: string;
  readonly kind: "integer" | "float" | "categorical";
  readonly default: SearchScalar;
  readonly low: number | null;
  readonly high: number | null;
  readonly step: number | null;
  readonly choices: readonly SearchScalar[];
  readonly log_scale: boolean;
}

export interface AutoMLAlgorithm {
  readonly id: string;
  readonly display_name: string;
  readonly task_type: AutoMLTask;
  readonly probability_support: boolean;
  readonly parameters: readonly AutoMLSearchParameter[];
}

export type AutoMLRequestSearchParameter =
  | {
      readonly name: string;
      readonly kind: "integer";
      readonly default: number;
      readonly low: number;
      readonly high: number;
      readonly step: number;
      readonly log_scale: false;
    }
  | {
      readonly name: string;
      readonly kind: "float";
      readonly default: number;
      readonly low: number;
      readonly high: number;
      readonly step: number | null;
      readonly log_scale: boolean;
    }
  | {
      readonly name: string;
      readonly kind: "categorical";
      readonly default: SearchScalar;
      readonly choices: readonly SearchScalar[];
    };

export interface AutoMLSearchSpace {
  readonly plugin_id: string;
  readonly task_type: AutoMLTask;
  readonly probability_support: boolean;
  readonly parameters: readonly AutoMLRequestSearchParameter[];
}

export interface AutoMLStudySummary {
  readonly study_id: string;
  readonly requested_by_user_id: string;
  readonly task_type: AutoMLTask;
  readonly status: AutoMLStudyStatus;
  readonly primary_metric: string;
  readonly metric_direction: MetricDirection;
  readonly plugin_ids: readonly string[];
  readonly trial_budget: number;
  readonly created_at: string;
  readonly started_at: string | null;
  readonly finished_at: string | null;
  readonly cancel_requested_at: string | null;
}

export interface AutoMLStudyDetail extends AutoMLStudySummary {
  readonly random_seed: number;
  readonly sampler_type: "random";
  readonly search_spaces: readonly Readonly<Record<string, unknown>>[];
  readonly preprocessing: Readonly<Record<string, unknown>>;
  readonly data_specification: Readonly<Record<string, unknown>>;
  readonly cross_validation_folds: number;
  readonly time_budget_seconds: number;
  readonly per_trial_timeout_seconds: number;
  readonly max_concurrent_trials: number;
  readonly register_champion: boolean;
  readonly registered_model_name: string | null;
  readonly best_trial_id: string | null;
  readonly champion_training_job_id: string | null;
  readonly error_code: string | null;
  readonly safe_error_message: string | null;
}

export interface AutoMLTrialSummary {
  readonly trial_id: string;
  readonly study_id: string;
  readonly trial_number: number;
  readonly plugin_id: string;
  readonly status: AutoMLTrialStatus;
  readonly primary_metric_value: number | null;
  readonly duration_seconds: number | null;
  readonly created_at: string;
  readonly started_at: string | null;
  readonly finished_at: string | null;
}

export interface AutoMLTrialDetail extends AutoMLTrialSummary {
  readonly parameters: Readonly<Record<string, unknown>>;
  readonly attempt_count: number;
  readonly max_attempts: number;
  readonly fold_metrics: readonly Readonly<Record<string, number>>[] | null;
  readonly aggregate_metrics: Readonly<Record<string, number>> | null;
  readonly error_code: string | null;
  readonly safe_error_message: string | null;
}

export interface AutoMLLeaderboardEntry {
  readonly rank: number;
  readonly trial_id: string;
  readonly trial_number: number;
  readonly plugin_id: string;
  readonly status: AutoMLTrialStatus;
  readonly primary_metric_value: number | null;
  readonly metric_standard_deviation: number | null;
  readonly duration_seconds: number | null;
  readonly parameters: Readonly<Record<string, unknown>>;
}

export interface AutoMLStudyPage {
  readonly items: readonly AutoMLStudySummary[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

export interface AutoMLTrialPage {
  readonly items: readonly AutoMLTrialSummary[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

export interface AutoMLStudySubmission {
  readonly study_id: string;
  readonly status: AutoMLStudyStatus;
  readonly submitted_at: string;
  readonly status_url: string;
  readonly created: boolean;
}

export interface AutoMLCancelResult {
  readonly study_id: string;
  readonly status: AutoMLStudyStatus;
  readonly cancellation: "cancelled" | "requested" | "unchanged";
  readonly cancel_requested_at: string | null;
  readonly cancelled_at: string | null;
}

export interface AutoMLStudyRequest {
  readonly task_type: AutoMLTask;
  readonly primary_metric: string;
  readonly metric_direction: MetricDirection;
  readonly sampler_type: "random";
  readonly random_seed: number;
  readonly plugin_ids: readonly string[];
  readonly plugin_search_spaces: readonly AutoMLSearchSpace[];
  readonly preprocessing: { readonly scaler: string; readonly imputer: string };
  readonly data: {
    readonly training_data_fingerprint: string;
    readonly evaluation_data_fingerprint: string;
    readonly training_row_count: number;
    readonly evaluation_row_count: number;
    readonly feature_count: number;
    readonly training_features: readonly (readonly number[])[];
    readonly training_targets: readonly number[];
    readonly evaluation_features: readonly (readonly number[])[];
    readonly evaluation_targets: readonly number[];
  };
  readonly budget: {
    readonly trial_budget: number;
    readonly time_budget_seconds: number;
    readonly per_trial_timeout_seconds: number;
    readonly max_concurrent_trials: number;
    readonly cross_validation_folds: number;
  };
  readonly register_champion: boolean;
  readonly registered_model_name: string | null;
}

function queryString(
  values: Readonly<Record<string, string | number | undefined>>,
): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  const encoded = query.toString();
  return encoded === "" ? "" : `?${encoded}`;
}

export const getAutoMLAlgorithms = (signal?: AbortSignal): Promise<AutoMLAlgorithm[]> =>
  apiRequest("/ai/automl/algorithms", { signal });

export function listAutoMLStudies(options: {
  readonly status?: AutoMLStudyStatus;
  readonly taskType?: AutoMLTask;
  readonly pluginId?: string;
  readonly requesterId?: string;
  readonly limit: number;
  readonly offset: number;
  readonly signal?: AbortSignal;
}): Promise<AutoMLStudyPage> {
  return apiRequest(
    `/ai/automl/studies${queryString({ status: options.status, task_type: options.taskType, plugin_id: options.pluginId, requester_id: options.requesterId, limit: options.limit, offset: options.offset })}`,
    { signal: options.signal },
  );
}

export const getAutoMLStudy = (id: string, signal?: AbortSignal) =>
  apiRequest<AutoMLStudyDetail>(`/ai/automl/studies/${encodeURIComponent(id)}`, {
    signal,
  });

export function listAutoMLTrials(options: {
  readonly studyId: string;
  readonly status?: AutoMLTrialStatus;
  readonly pluginId?: string;
  readonly order?: "trial_number" | "metric_desc";
  readonly limit: number;
  readonly offset: number;
  readonly signal?: AbortSignal;
}): Promise<AutoMLTrialPage> {
  return apiRequest(
    `/ai/automl/studies/${encodeURIComponent(options.studyId)}/trials${queryString({ status: options.status, plugin_id: options.pluginId, order: options.order, limit: options.limit, offset: options.offset })}`,
    { signal: options.signal },
  );
}

export const getAutoMLTrial = (
  studyId: string,
  trialId: string,
  signal?: AbortSignal,
) =>
  apiRequest<AutoMLTrialDetail>(
    `/ai/automl/studies/${encodeURIComponent(studyId)}/trials/${encodeURIComponent(trialId)}`,
    { signal },
  );

export const getAutoMLLeaderboard = (studyId: string, signal?: AbortSignal) =>
  apiRequest<AutoMLLeaderboardEntry[]>(
    `/ai/automl/studies/${encodeURIComponent(studyId)}/leaderboard`,
    { signal },
  );

export const createAutoMLStudy = (
  payload: AutoMLStudyRequest,
  idempotencyKey: string,
): Promise<AutoMLStudySubmission> =>
  apiRequest("/ai/automl/studies", {
    body: JSON.stringify(payload),
    headers: { "Idempotency-Key": idempotencyKey },
    method: "POST",
  });

export const cancelAutoMLStudy = (studyId: string): Promise<AutoMLCancelResult> =>
  apiRequest(`/ai/automl/studies/${encodeURIComponent(studyId)}/cancel`, {
    method: "POST",
  });
