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
  readonly dataset_version_id: string | null;
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

interface TrainingRequestMetadata {
  readonly hyperparameters: Record<string, unknown>;
  readonly random_seed: number | null;
  readonly experiment_name: string;
  readonly run_name: string | null;
  readonly registered_model_name: string | null;
  readonly tags: Record<string, string>;
  readonly model_description: string | null;
}

interface InlineTrainingData {
  readonly dataset_version_id?: never;
  readonly training_features: number[][];
  readonly training_targets: number[];
  readonly evaluation_features: number[][];
  readonly evaluation_targets: number[];
}

interface RegisteredTrainingData {
  readonly dataset_version_id: string;
  readonly training_features?: never;
  readonly training_targets?: never;
  readonly evaluation_features?: never;
  readonly evaluation_targets?: never;
}

export type TrainingRequest = TrainingRequestMetadata &
  (InlineTrainingData | RegisteredTrainingData);

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

// ─── Evaluation plot shapes ──────────────────────────────────────────────────

export interface ConfusionMatrixPlot {
  readonly labels: readonly string[];
  readonly values: readonly (readonly number[])[];
}

export interface XYThresholdPoint {
  readonly x: number;
  readonly y: number;
  readonly threshold: number | null;
}

export interface XYPoint {
  readonly x: number;
  readonly y: number;
}

export interface HistogramBin {
  readonly start: number;
  readonly end: number;
  readonly count: number;
}

export interface ClassDistributionItem {
  readonly label: string;
  readonly count: number;
}

export interface ActualVsPredictedPoint {
  readonly actual: number;
  readonly predicted: number;
}

export interface ResidualPoint {
  readonly predicted: number;
  readonly residual: number;
}

export interface ErrorByRangePoint {
  readonly start: number;
  readonly end: number;
  readonly mean_absolute_error: number;
  readonly count: number;
}

export interface RankedFeature {
  readonly feature: string;
  readonly value: number;
}

export interface UnsupportedExplain {
  readonly supported: false;
  readonly reason: string;
}

export type ExplainabilityEntry = readonly RankedFeature[] | UnsupportedExplain;

export interface ClassificationPlots {
  readonly confusion_matrix?: ConfusionMatrixPlot;
  readonly class_distribution?: readonly ClassDistributionItem[];
  readonly roc_curve?: readonly XYThresholdPoint[];
  readonly precision_recall_curve?: readonly XYThresholdPoint[];
  readonly calibration?: readonly XYPoint[];
  readonly probability_distribution?: readonly HistogramBin[];
}

export interface RegressionPlots {
  readonly actual_vs_predicted?: readonly ActualVsPredictedPoint[];
  readonly residuals?: readonly ResidualPoint[];
  readonly residual_distribution?: readonly HistogramBin[];
  readonly absolute_error_distribution?: readonly HistogramBin[];
  readonly error_by_prediction_range?: readonly ErrorByRangePoint[];
}

export type EvaluationPlots = ClassificationPlots & RegressionPlots;

export interface Explainability {
  readonly native_feature_importance?: ExplainabilityEntry;
  readonly coefficients?: ExplainabilityEntry;
  readonly permutation_importance?: ExplainabilityEntry;
  readonly local?: UnsupportedExplain;
  readonly notice?: string;
}

// ─── Classification report ────────────────────────────────────────────────────

export interface ClassReportRow {
  readonly precision: number;
  readonly recall: number;
  readonly "f1-score": number;
  readonly support: number;
}

export type ClassificationReport = Record<string, ClassReportRow | number>;

// ─── Evaluation payload ───────────────────────────────────────────────────────

export interface EvaluationPayload {
  readonly schema_version: string;
  readonly task_type: TrainingTask;
  readonly algorithm: string;
  readonly sample_count: number;
  readonly feature_count: number;
  readonly metrics?: Record<string, number> | null;
  readonly plots?: EvaluationPlots | null;
  readonly omitted?: Record<string, string> | null;
  readonly omitted_metrics?: Record<string, string> | null;
  readonly explainability?: Explainability | null;
  readonly classification_report?: ClassificationReport;
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
