import { apiDownload, apiRequest } from "./client";

export interface AuditEvent {
  readonly action: string;
  readonly actor_role: string | null;
  readonly actor_user_id: string | null;
  readonly after_summary: string | null;
  readonly before_summary: string | null;
  readonly correlation_id: string | null;
  readonly id: string;
  readonly occurred_at: string;
  readonly request_id: string | null;
  readonly resource_id: string | null;
  readonly resource_type: string;
  readonly result: "success" | "failure";
  readonly retention_class: string;
  readonly safe_metadata: Readonly<Record<string, unknown>>;
  readonly source_ip: string | null;
  readonly user_agent: string | null;
}

export interface AuditPage {
  readonly items: readonly AuditEvent[];
  readonly limit: number;
  readonly offset: number;
  readonly total: number;
}

export function listAuditEvents(query: {
  readonly action?: string;
  readonly offset: number;
  readonly resourceType?: string;
  readonly result?: "success" | "failure";
  readonly signal?: AbortSignal;
}): Promise<AuditPage> {
  const params = new URLSearchParams({
    limit: "50",
    offset: String(query.offset),
  });
  if (query.action) params.set("action", query.action);
  if (query.resourceType) params.set("resource_type", query.resourceType);
  if (query.result) params.set("result", query.result);
  return apiRequest<AuditPage>(`/audit-events?${params}`, {
    signal: query.signal,
  });
}

export async function downloadAuditEvents(format: "csv" | "json"): Promise<void> {
  const blob = await apiDownload(`/audit-events/export?export_format=${format}`);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `audit-events.${format}`;
  link.click();
  URL.revokeObjectURL(url);
}
