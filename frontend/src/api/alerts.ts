import { apiRequest } from "./client";

export type AlertSeverity = "critical" | "warning";
export type AlertStatus = "acknowledged" | "open" | "resolved";
export interface MonitoringAlert {
  readonly id: string;
  readonly alert_type: string;
  readonly severity: AlertSeverity;
  readonly registered_model_name: string;
  readonly model_version: string;
  readonly monitoring_evaluation_id: string | null;
  readonly title: string;
  readonly safe_summary: string;
  readonly status: AlertStatus;
  readonly first_detected_at: string;
  readonly last_detected_at: string;
  readonly occurrence_count: number;
  readonly acknowledged_at: string | null;
  readonly acknowledged_by_user_id: string | null;
  readonly resolved_at: string | null;
  readonly created_at: string;
  readonly updated_at: string;
  readonly factory_id: string | null;
  readonly machine_id: string | null;
  readonly operator_note: string | null;
  readonly engineer_note: string | null;
  readonly cooldown_until: string | null;
}
export interface AlertPage {
  readonly items: readonly MonitoringAlert[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

export function listAlerts(options: {
  readonly limit: number;
  readonly modelName?: string;
  readonly offset: number;
  readonly severity?: AlertSeverity;
  readonly signal?: AbortSignal;
  readonly status?: AlertStatus;
  readonly version?: string;
}): Promise<AlertPage> {
  const q = new URLSearchParams({
    limit: String(options.limit),
    offset: String(options.offset),
  });
  if (options.modelName) q.set("registered_model_name", options.modelName);
  if (options.version) q.set("model_version", options.version);
  if (options.severity) q.set("severity", options.severity);
  if (options.status) q.set("status", options.status);
  return apiRequest(`/ai/monitoring/alerts?${q.toString()}`, {
    signal: options.signal,
  });
}
export const getAlert = (id: string, signal?: AbortSignal): Promise<MonitoringAlert> =>
  apiRequest(`/ai/monitoring/alerts/${encodeURIComponent(id)}`, { signal });
export const acknowledgeAlert = (
  id: string,
  operatorNote?: string,
): Promise<MonitoringAlert> =>
  apiRequest(`/ai/monitoring/alerts/${encodeURIComponent(id)}/acknowledge`, {
    method: "POST",
    body: JSON.stringify({ operator_note: operatorNote || null }),
  });
export const resolveAlert = (
  id: string,
  engineerNote?: string,
): Promise<MonitoringAlert> =>
  apiRequest(`/ai/monitoring/alerts/${encodeURIComponent(id)}/resolve`, {
    method: "POST",
    body: JSON.stringify({ engineer_note: engineerNote || null }),
  });
