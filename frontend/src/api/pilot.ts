import { apiRequest } from "./client";

export interface MachineRisk {
  readonly alert_id: string | null;
  readonly acknowledged_at: string | null;
  readonly acknowledged_by_user_id: string | null;
  readonly assessed_at: string;
  readonly data_freshness_seconds: number | null;
  readonly factory_id: string;
  readonly id: string;
  readonly machine_id: string;
  readonly model_version: string;
  readonly monitoring_status: string;
  readonly recommended_action: string;
  readonly registered_model_name: string;
  readonly risk_score: number | null;
  readonly risk_state: string;
  readonly sensor_values: readonly Readonly<Record<string, unknown>>[];
}

export function getMachineRisk(
  machineId: string,
  signal?: AbortSignal,
): Promise<MachineRisk> {
  return apiRequest<MachineRisk>(`/pilot/machines/${machineId}/risk`, { signal });
}

export function acknowledgeMachineRisk(
  assessmentId: string,
  operatorNote: string,
): Promise<void> {
  return apiRequest<void>(`/pilot/machine-risk/${assessmentId}/acknowledge`, {
    method: "POST",
    body: JSON.stringify({ operator_note: operatorNote || null }),
  });
}
