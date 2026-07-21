import { apiRequest } from "./client";

export type TrainingJobStatus =
  "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type TrainingTask = "regression" | "classification";

export interface TrainerKey {
  readonly algorithm: string;
  readonly task_type: TrainingTask;
}

export interface TrainingJobSubmission {
  readonly job_id: string;
  readonly status: TrainingJobStatus;
  readonly submitted_at: string;
  readonly status_url: string;
}

export interface TrainingJob {
  readonly job_id: string;
  readonly requested_by_user_id: string;
  readonly trainer_key: TrainerKey;
  readonly status: TrainingJobStatus;
  readonly created_at: string;
  readonly queued_at: string;
  readonly started_at: string | null;
  readonly finished_at: string | null;
  readonly cancelled_at: string | null;
  readonly attempt_count: number;
  readonly max_attempts: number;
  readonly metrics: Record<string, number> | null;
  readonly local_execution_run_id: string | null;
  readonly mlflow_experiment_id: string | null;
  readonly mlflow_run_id: string | null;
  readonly registered_model_name: string;
  readonly registered_model_version: string | null;
  readonly error_code: string | null;
  readonly safe_error_message: string | null;
}

export interface TrainingJobPage {
  readonly items: readonly TrainingJob[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

export interface TrainingRequest {
  readonly training_features: number[][];
  readonly training_targets: number[];
  readonly evaluation_features: number[][];
  readonly evaluation_targets: number[];
  readonly hyperparameters: Record<string, unknown>;
  readonly random_seed: number | null;
  readonly experiment_name: string;
  readonly run_name: string | null;
  readonly registered_model_name: string | null;
  readonly tags: Record<string, string>;
  readonly model_description: string | null;
}

export interface AlgorithmParameter {
  readonly name: string;
  readonly type: "integer" | "number" | "boolean" | "choice";
  readonly default: number | boolean | string;
  readonly minimum: number | null;
  readonly maximum: number | null;
  readonly choices: readonly string[];
  readonly description: string;
}

export interface Algorithm {
  readonly id: string;
  readonly algorithm_family: string;
  readonly display_name: string;
  readonly description: string;
  readonly supported_tasks: readonly TrainingTask[];
  readonly parameters: readonly AlgorithmParameter[];
  readonly default_parameters: Record<string, number | boolean | string>;
  readonly scaling_behavior: "auto" | "none" | "standard" | "minmax" | "robust";
  readonly probability_support: boolean;
  readonly decision_function_support: boolean;
  readonly feature_importance_support: boolean;
  readonly coefficient_support: boolean;
  readonly permutation_importance_support: boolean;
  readonly global_explainability: boolean;
  readonly local_explainability: boolean;
  readonly dependency_available: boolean;
}

export interface EvaluationPayload {
  readonly schema_version: string;
  readonly task_type: TrainingTask;
  readonly algorithm: string;
  readonly sample_count: number;
  readonly feature_count: number;
  readonly metrics: Record<string, number>;
  readonly plots: Record<string, unknown>;
  readonly omitted: Record<string, string>;
  readonly explainability: Record<string, unknown>;
  readonly classification_report?: Record<string, unknown>;
}

export interface ModelVersion {
  readonly model_name: string;
  readonly model_version: string;
  readonly run_id: string;
  readonly trainer_key: TrainerKey;
  readonly status: string;
  readonly aliases: readonly string[];
}

export interface ModelAlias {
  readonly alias: string;
  readonly version: string;
}

export interface ModelAliases {
  readonly registered_model_name: string;
  readonly aliases: readonly ModelAlias[];
}

export interface PromotionAudit {
  readonly audit_id: string;
  readonly registered_model_name: string;
  readonly model_version: string;
  readonly trainer_key: TrainerKey;
  readonly target_alias: string;
  readonly previous_version: string | null;
  readonly requested_by_user_id: string;
  readonly action: string;
  readonly decision: string;
  readonly policy_result: Record<string, unknown>;
  readonly force: boolean;
  readonly reason: string | null;
  readonly operation_outcome: string;
  readonly created_at: string;
  readonly completed_at: string | null;
  readonly error_code: string | null;
  readonly safe_error_message: string | null;
}

export interface PromotionAuditPage {
  readonly items: readonly PromotionAudit[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

export interface PromotionResult {
  readonly audit_id: string;
  readonly registered_model_name: string;
  readonly selected_version: string;
  readonly target_alias: string;
  readonly previous_version: string | null;
  readonly policy_evaluation: {
    readonly accepted: boolean;
    readonly reason: string;
    readonly primary_metric: string;
    readonly candidate_value: number | null;
    readonly incumbent_value: number | null;
    readonly improvement: number | null;
    readonly safeguards: Record<string, boolean>;
  };
  readonly overridden: boolean;
  readonly completed_at: string;
}

function queryString(values: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined) query.set(key, String(value));
  });
  return query.toString();
}

export function listTrainingJobs(options: {
  readonly limit: number;
  readonly offset: number;
  readonly signal?: AbortSignal;
  readonly status?: TrainingJobStatus;
}): Promise<TrainingJobPage> {
  return apiRequest<TrainingJobPage>(
    `/ai/training-jobs?${queryString({ limit: options.limit, offset: options.offset, status: options.status })}`,
    { signal: options.signal },
  );
}

export function getTrainingJob(id: string, signal?: AbortSignal): Promise<TrainingJob> {
  return apiRequest<TrainingJob>(`/ai/training-jobs/${encodeURIComponent(id)}`, {
    signal,
  });
}

export function createTrainingJob(
  task: TrainingTask,
  payload: TrainingRequest,
  algorithm?: string,
  preprocessing: { readonly scaler: string; readonly imputer: string } = {
    scaler: "auto",
    imputer: "none",
  },
): Promise<TrainingJobSubmission> {
  const path = algorithm
    ? "/ai/training-jobs"
    : `/ai/training-jobs/random-forest/${task}`;
  const body = algorithm
    ? { ...payload, algorithm, preprocessing, task_type: task }
    : payload;
  return apiRequest<TrainingJobSubmission>(path, {
    body: JSON.stringify(body),
    method: "POST",
  });
}

export function listAlgorithms(signal?: AbortSignal): Promise<readonly Algorithm[]> {
  return apiRequest<readonly Algorithm[]>("/ai/algorithms", { signal });
}

export function getTrainingEvaluation(
  id: string,
  signal?: AbortSignal,
): Promise<EvaluationPayload> {
  return apiRequest<EvaluationPayload>(
    `/ai/training-jobs/${encodeURIComponent(id)}/evaluation`,
    { signal },
  );
}

export function cancelTrainingJob(id: string): Promise<TrainingJob> {
  return apiRequest<TrainingJob>(`/ai/training-jobs/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
  });
}

const modelPath = (name: string): string => `/ai/models/${encodeURIComponent(name)}`;

export function getModelVersion(
  name: string,
  version: string,
  signal?: AbortSignal,
): Promise<ModelVersion> {
  return apiRequest<ModelVersion>(
    `${modelPath(name)}/versions/${encodeURIComponent(version)}`,
    { signal },
  );
}

export function getModelAliases(
  name: string,
  signal?: AbortSignal,
): Promise<ModelAliases> {
  return apiRequest<ModelAliases>(`${modelPath(name)}/aliases`, { signal });
}

export function listPromotions(
  name: string,
  options: {
    readonly limit: number;
    readonly offset: number;
    readonly signal?: AbortSignal;
  },
): Promise<PromotionAuditPage> {
  return apiRequest<PromotionAuditPage>(
    `${modelPath(name)}/promotions?${queryString({ limit: options.limit, offset: options.offset })}`,
    { signal: options.signal },
  );
}

export function promoteModel(
  name: string,
  version: string,
  target: "challenger" | "champion",
  payload: { readonly force: boolean; readonly reason: string | null },
): Promise<PromotionResult> {
  return apiRequest<PromotionResult>(
    `${modelPath(name)}/versions/${encodeURIComponent(version)}/promotions/${target}`,
    { body: JSON.stringify(payload), method: "POST" },
  );
}
