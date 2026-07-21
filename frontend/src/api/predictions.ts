import { apiRequest } from "./client";
import type { TrainerKey, TrainingTask } from "./aiLifecycle";

export type PredictionEventStatus = "failed" | "succeeded";

export interface PredictionRequest {
  readonly registered_model_name: string;
  readonly version_or_alias: string;
  readonly features: number[][];
}

export interface ClassProbability {
  readonly class_label: string;
  readonly probability: number;
}

export interface PredictionResponse {
  readonly model_name: string;
  readonly model_version: string;
  readonly trainer_key: TrainerKey;
  readonly predictions: readonly number[];
  /** Only present for classifiers with probability_support=true */
  readonly probabilities?: readonly (readonly ClassProbability[])[] | null;
  /** Whether the model supports class probabilities */
  readonly probability_available?: boolean;
  /** Reason when probability_available is false */
  readonly probability_unavailable_reason?: string | null;
}

export interface NumericSummary {
  readonly count: number;
  readonly missing_count: number;
  readonly finite_count: number;
  readonly non_finite_count: number;
  readonly minimum: number | null;
  readonly maximum: number | null;
  readonly mean: number | null;
  readonly standard_deviation: number | null;
  readonly quantiles: Readonly<Record<string, number>>;
}

export interface PredictionEvent {
  readonly event_id: string;
  readonly registered_model_name: string;
  readonly requested_model_reference: string;
  readonly resolved_model_version: string | null;
  readonly resolved_aliases: readonly string[];
  readonly trainer_key: TrainerKey;
  readonly status: PredictionEventStatus;
  readonly row_count: number;
  readonly feature_count: number;
  readonly duration_ms: number;
  readonly feature_profile: readonly unknown[];
  readonly prediction_profile: unknown | null;
  readonly error_code: string | null;
  readonly safe_error_message: string | null;
  readonly correlation_id: string | null;
  readonly created_at: string;
  readonly completed_at: string;
}

export interface PredictionEventPage {
  readonly items: readonly PredictionEvent[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

export interface PredictionOutcomeInput {
  readonly actual_value: number;
  readonly observed_at: string;
  readonly source: string;
  readonly label_maturity_at: string;
  readonly safe_metadata: Readonly<Record<string, string>>;
  readonly external_reference_key: string | null;
}

export interface PredictionOutcome extends PredictionOutcomeInput {
  readonly id: string;
  readonly prediction_event_id: string;
  readonly outcome_type: TrainingTask;
  readonly created_at: string;
  readonly updated_at: string;
}

function query(values: Record<string, string | number | undefined>): string {
  const result = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== "") result.set(key, String(value));
  });
  const encoded = result.toString();
  return encoded ? `?${encoded}` : "";
}

export function executePrediction(
  task: TrainingTask,
  payload: PredictionRequest,
  correlationId?: string,
  algorithm?: string,
): Promise<PredictionResponse> {
  const generic = algorithm && !algorithm.startsWith("random_forest_");
  return apiRequest(
    generic ? "/ai/predictions" : `/ai/predictions/random-forest/${task}`,
    {
      body: JSON.stringify(
        generic ? { ...payload, algorithm, task_type: task } : payload,
      ),
      headers: correlationId ? { "X-Correlation-ID": correlationId } : undefined,
      method: "POST",
    },
  );
}

export function listPredictionEvents(options: {
  readonly endAt?: string;
  readonly limit: number;
  readonly modelName?: string;
  readonly offset: number;
  readonly signal?: AbortSignal;
  readonly startAt?: string;
  readonly status?: PredictionEventStatus;
  readonly taskType?: TrainingTask;
  readonly version?: string;
}): Promise<PredictionEventPage> {
  return apiRequest(
    `/ai/monitoring/prediction-events${query({ end_at: options.endAt, limit: options.limit, offset: options.offset, registered_model_name: options.modelName, resolved_model_version: options.version, start_at: options.startAt, status: options.status, task_type: options.taskType })}`,
    { signal: options.signal },
  );
}

export function getPredictionEvent(
  id: string,
  signal?: AbortSignal,
): Promise<PredictionEvent> {
  return apiRequest(`/ai/monitoring/prediction-events/${encodeURIComponent(id)}`, {
    signal,
  });
}

export function submitPredictionOutcome(
  eventId: string,
  payload: PredictionOutcomeInput,
): Promise<PredictionOutcome> {
  return apiRequest(
    `/ai/monitoring/prediction-events/${encodeURIComponent(eventId)}/outcome`,
    {
      body: JSON.stringify(payload),
      method: "PUT",
    },
  );
}
