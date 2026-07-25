import { apiDownload, apiRequest } from "./client";

export interface DataImport {
  readonly completed_at: string | null;
  readonly created_at: string;
  readonly delimiter: string;
  readonly error_samples: readonly Record<string, unknown>[];
  readonly filename: string;
  readonly id: string;
  readonly imported_rows: number;
  readonly mapping: Record<string, unknown>;
  readonly preview: readonly Record<string, unknown>[];
  readonly progress_percent: number;
  readonly quality_report: Record<string, unknown>;
  readonly rejected_rows: number;
  readonly size_bytes: number;
  readonly status: string;
  readonly total_rows: number;
}

export interface DataImportPage {
  readonly items: readonly DataImport[];
  readonly limit: number;
  readonly offset: number;
  readonly total: number;
}

export interface ImportMapping {
  readonly batch_or_shift?: string;
  readonly features?: readonly string[];
  readonly machine: string;
  readonly operating_state?: string;
  readonly sensor?: string;
  readonly shape: "long" | "wide";
  readonly target?: string;
  readonly timestamp: string;
  readonly value?: string;
}

export function uploadGuidedCsv(
  file: File,
  idempotencyKey: string,
): Promise<DataImport> {
  const body = new FormData();
  body.append("file", file, file.name);
  return apiRequest("/data-onboarding/imports", {
    body,
    headers: { "Idempotency-Key": idempotencyKey },
    method: "POST",
  });
}

export function listGuidedImports(signal?: AbortSignal): Promise<DataImportPage> {
  return apiRequest("/data-onboarding/imports?limit=25", { signal });
}

export function saveImportMapping(
  id: string,
  mapping: ImportMapping,
  delimiter = ",",
): Promise<DataImport> {
  return apiRequest(`/data-onboarding/imports/${id}/mapping`, {
    body: JSON.stringify({ delimiter, has_header: true, mapping }),
    method: "PUT",
  });
}

export function validateImport(id: string): Promise<DataImport> {
  return apiRequest(`/data-onboarding/imports/${id}/validate`, { method: "POST" });
}

export function confirmImport(
  id: string,
  acceptWarnings: boolean,
): Promise<DataImport> {
  return apiRequest(`/data-onboarding/imports/${id}/confirm`, {
    body: JSON.stringify({ accept_warnings: acceptWarnings }),
    method: "POST",
  });
}

export function downloadImportQuality(
  id: string,
  format: "csv" | "json" = "csv",
): Promise<Blob> {
  return apiDownload(`/data-onboarding/imports/${id}/quality.${format}`);
}

export interface ReadinessResult {
  readonly blocking_issues: readonly string[];
  readonly dataset_size: number;
  readonly deployment_consequence: string;
  readonly missingness_rate: number;
  readonly profile_summary: string;
  readonly ready: boolean;
  readonly selected_features: readonly string[];
  readonly target_available: boolean;
  readonly valid_rows: number;
}

export function checkGuidedReadiness(payload: {
  readonly features: readonly string[];
  readonly import_id: string;
  readonly profile: "balanced" | "fast_demo" | "thorough";
  readonly target?: string;
  readonly use_case:
    | "condition_monitoring"
    | "energy_monitoring"
    | "predictive_maintenance"
    | "quality_prediction";
}): Promise<ReadinessResult> {
  return apiRequest("/data-onboarding/guided-ai/readiness", {
    body: JSON.stringify(payload),
    method: "POST",
  });
}

export interface DemoRun {
  readonly current_step: number;
  readonly factory_id: string;
  readonly generated_readings: number;
  readonly id: string;
  readonly machine_id: string;
  readonly scenario: string;
  readonly speed: number;
  readonly state_snapshot: Record<string, unknown>;
  readonly status: string;
}

export function startDemoRun(payload: {
  readonly factory_id: string;
  readonly idempotency_key: string;
  readonly machine_id: string;
  readonly scenario: string;
  readonly speed: number;
}): Promise<DemoRun> {
  return apiRequest("/demo/runs", {
    body: JSON.stringify(payload),
    method: "POST",
  });
}

export function getDemoRun(id: string, signal?: AbortSignal): Promise<DemoRun> {
  return apiRequest(`/demo/runs/${id}`, { signal });
}

export function advanceDemoRun(id: string): Promise<DemoRun> {
  return apiRequest(`/demo/runs/${id}/advance`, { method: "POST" });
}

export function controlDemoRun(
  id: string,
  command: "pause" | "resume" | "stop",
): Promise<DemoRun> {
  return apiRequest(`/demo/runs/${id}/${command}`, { method: "POST" });
}

export function resetDemoRun(
  id: string,
): Promise<{ readonly deleted_records: number }> {
  return apiRequest(`/demo/runs/${id}/reset`, { method: "DELETE" });
}

export interface FactoryLayout {
  readonly factory_id: string;
  readonly id: string;
  readonly nodes: readonly {
    readonly group?: string;
    readonly machine_id: string;
    readonly x: number;
    readonly y: number;
  }[];
  readonly updated_at: string;
  readonly version: number;
}

export function getFactoryLayout(
  factoryId: string,
  signal?: AbortSignal,
): Promise<FactoryLayout | null> {
  return apiRequest(`/demo/factories/${factoryId}/layout`, { signal });
}

export function saveFactoryLayout(
  factoryId: string,
  nodes: FactoryLayout["nodes"],
): Promise<FactoryLayout> {
  return apiRequest(`/demo/factories/${factoryId}/layout`, {
    body: JSON.stringify({ nodes }),
    method: "PUT",
  });
}

export function getTvSummary(
  factoryId: string,
  signal?: AbortSignal,
): Promise<Readonly<Record<string, unknown>>> {
  return apiRequest(`/demo/factories/${factoryId}/tv`, { signal });
}

export interface FactoryMapState {
  readonly action_count: number;
  readonly alert_count: number;
  readonly assessed_at: string | null;
  readonly machine_id: string;
  readonly machine_name: string;
  readonly state: string;
}

export function getFactoryMapState(
  factoryId: string,
  signal?: AbortSignal,
): Promise<readonly FactoryMapState[]> {
  return apiRequest(`/demo/factories/${factoryId}/map-state`, { signal });
}

export interface ExecutiveDashboard {
  readonly definitions: Readonly<Record<string, string>>;
  readonly drill_downs: Readonly<Record<string, string>>;
  readonly limitations: string;
  readonly metrics: Readonly<Record<string, number | string | null>>;
  readonly source: string;
}

export function getExecutiveDashboard(
  signal?: AbortSignal,
): Promise<ExecutiveDashboard> {
  return apiRequest("/reporting/executive-dashboard", { signal });
}

export interface ReportJob {
  readonly completed_at: string | null;
  readonly created_at: string;
  readonly expires_at: string | null;
  readonly factory_id: string | null;
  readonly format: "csv" | "pdf" | "xlsx";
  readonly id: string;
  readonly period_end: string;
  readonly period_start: string;
  readonly report_type: string;
  readonly safe_error: string | null;
  readonly size_bytes: number | null;
  readonly status: string;
  readonly summary: Readonly<Record<string, unknown>>;
}

export function listReports(signal?: AbortSignal): Promise<readonly ReportJob[]> {
  return apiRequest("/reporting/reports", { signal });
}

export function getReport(id: string, signal?: AbortSignal): Promise<ReportJob> {
  return apiRequest(`/reporting/reports/${id}`, { signal });
}

export function createReport(payload: {
  readonly factory_id?: string;
  readonly format: "csv" | "pdf" | "xlsx";
  readonly idempotency_key: string;
  readonly period_end: string;
  readonly period_start: string;
  readonly report_type: string;
}): Promise<ReportJob> {
  return apiRequest("/reporting/reports", {
    body: JSON.stringify(payload),
    method: "POST",
  });
}

export function downloadReport(id: string): Promise<Blob> {
  return apiDownload(`/reporting/reports/${id}/download`);
}
