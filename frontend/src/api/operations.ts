import { apiRequest } from "./client";

export type ActionPriority = "critical" | "high" | "medium" | "low";
export type ActionStatus =
  "open" | "assigned" | "in_progress" | "blocked" | "completed" | "cancelled";
export type FeedbackOutcome =
  | "true_issue"
  | "false_alarm"
  | "sensor_fault"
  | "maintenance_performed"
  | "no_action_required"
  | "machine_stopped"
  | "other";
export type ShiftStatus = "active" | "ended" | "acknowledged";

export interface OperationalAction {
  readonly acknowledged_at: string | null;
  readonly assigned_user_id: string | null;
  readonly company_id: string;
  readonly completed_at: string | null;
  readonly completion_summary: string | null;
  readonly created_at: string;
  readonly created_by: string;
  readonly due_at: string | null;
  readonly factory_id: string;
  readonly id: string;
  readonly machine_id: string;
  readonly priority: ActionPriority;
  readonly reason: string;
  readonly recommended_action: string;
  readonly related_alert_id: string | null;
  readonly started_at: string | null;
  readonly status: ActionStatus;
  readonly title: string;
  readonly updated_at: string;
  readonly version: number;
}

export interface OperationalActionPage {
  readonly items: readonly OperationalAction[];
  readonly limit: number;
  readonly offset: number;
  readonly total: number;
}

export interface OperationalAlert {
  readonly acknowledged_at: string | null;
  readonly assigned_at: string | null;
  readonly assigned_user_id: string | null;
  readonly company_id: string;
  readonly escalated_at: string | null;
  readonly factory_id: string | null;
  readonly first_detected_at: string;
  readonly id: string;
  readonly in_progress_at: string | null;
  readonly last_detected_at: string;
  readonly lifecycle_version: number;
  readonly machine_id: string | null;
  readonly occurrence_count: number;
  readonly reopened_at: string | null;
  readonly resolution_classification: string | null;
  readonly resolution_summary: string | null;
  readonly resolved_at: string | null;
  readonly safe_summary: string;
  readonly severity: string;
  readonly status: string;
  readonly title: string;
}

export interface OperationalAlertPage {
  readonly items: readonly OperationalAlert[];
  readonly limit: number;
  readonly offset: number;
  readonly total: number;
}

export interface OperationalNote {
  readonly action_id: string | null;
  readonly alert_id: string | null;
  readonly author_user_id: string;
  readonly body: string;
  readonly company_id: string;
  readonly created_at: string;
  readonly factory_id: string;
  readonly id: string;
  readonly kind: "operator" | "engineer";
  readonly machine_id: string;
}

export interface MaintenanceFeedback {
  readonly action_id: string | null;
  readonly alert_id: string | null;
  readonly company_id: string;
  readonly created_at: string;
  readonly downtime_minutes: number | null;
  readonly factory_id: string;
  readonly id: string;
  readonly machine_id: string;
  readonly maintenance_category: string | null;
  readonly outcome: FeedbackOutcome;
  readonly replaced_component: string | null;
  readonly submitted_by_user_id: string;
  readonly summary: string;
}

export interface TimelineEvent {
  readonly action_id: string | null;
  readonly actor_user_id: string | null;
  readonly alert_id: string | null;
  readonly company_id: string;
  readonly detail: string;
  readonly event_type: string;
  readonly factory_id: string;
  readonly id: string;
  readonly machine_id: string;
  readonly occurred_at: string;
  readonly safe_metadata: Readonly<Record<string, unknown>>;
  readonly title: string;
}

export interface TimelinePage {
  readonly items: readonly TimelineEvent[];
  readonly limit: number;
  readonly offset: number;
  readonly total: number;
}

export interface ShiftHandover {
  readonly acknowledged_at: string | null;
  readonly acknowledged_by_user_id: string | null;
  readonly company_id: string;
  readonly created_at: string;
  readonly ended_at: string | null;
  readonly ended_by_user_id: string | null;
  readonly factory_id: string;
  readonly handover_notes: string | null;
  readonly id: string;
  readonly snapshot: Readonly<Record<string, unknown>>;
  readonly started_at: string;
  readonly started_by_user_id: string;
  readonly status: ShiftStatus;
  readonly team_label: string | null;
  readonly unresolved_summary: string | null;
  readonly updated_at: string;
}

export interface ShiftPage {
  readonly items: readonly ShiftHandover[];
  readonly limit: number;
  readonly offset: number;
  readonly total: number;
}

export interface OperationalSummary {
  readonly action_counts: Readonly<Record<string, number>>;
  readonly active_shift_count: number;
  readonly alert_counts: Readonly<Record<string, number>>;
  readonly data_freshness_seconds: number | null;
  readonly overdue_actions: number;
  readonly risk_counts: Readonly<Record<string, number>>;
  readonly unassigned_urgent_actions: number;
}

export interface OperationalSearchResult {
  readonly description: string | null;
  readonly id: string;
  readonly label: string;
  readonly path: string;
  readonly resource_type:
    "factory" | "machine" | "sensor" | "alert" | "operational_action" | "user";
}

export interface OperationalAssignee {
  readonly email: string;
  readonly id: string;
  readonly role: string;
}

function queryString(
  values: Readonly<Record<string, boolean | number | string | undefined>>,
): string {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

export function listOperationalActions(
  options: {
    readonly assignedUserId?: string;
    readonly factoryId?: string;
    readonly limit?: number;
    readonly machineId?: string;
    readonly offset?: number;
    readonly overdue?: boolean;
    readonly priority?: ActionPriority;
    readonly signal?: AbortSignal;
    readonly status?: ActionStatus;
  } = {},
): Promise<OperationalActionPage> {
  return apiRequest(
    `/operations/actions${queryString({
      assigned_user_id: options.assignedUserId,
      factory_id: options.factoryId,
      limit: options.limit ?? 25,
      machine_id: options.machineId,
      offset: options.offset ?? 0,
      overdue: options.overdue,
      priority: options.priority,
      status: options.status,
    })}`,
    { signal: options.signal },
  );
}

export function getOperationalAction(
  id: string,
  signal?: AbortSignal,
): Promise<OperationalAction> {
  return apiRequest(`/operations/actions/${id}`, { signal });
}

export function createOperationalAction(payload: {
  readonly assigned_user_id?: string;
  readonly due_at?: string;
  readonly factory_id: string;
  readonly machine_id: string;
  readonly priority: ActionPriority;
  readonly reason: string;
  readonly recommended_action: string;
  readonly related_alert_id?: string;
  readonly title: string;
}): Promise<OperationalAction> {
  return apiRequest("/operations/actions", {
    body: JSON.stringify(payload),
    method: "POST",
  });
}

export function assignOperationalAction(
  id: string,
  assignedUserId: string,
  expectedVersion: number,
): Promise<OperationalAction> {
  return apiRequest(`/operations/actions/${id}/assign`, {
    body: JSON.stringify({
      assigned_user_id: assignedUserId,
      expected_version: expectedVersion,
    }),
    method: "POST",
  });
}

export function acknowledgeOperationalAction(
  id: string,
  expectedVersion: number,
  note?: string,
): Promise<OperationalAction> {
  return apiRequest(`/operations/actions/${id}/acknowledge`, {
    body: JSON.stringify({
      expected_version: expectedVersion,
      note: note || undefined,
    }),
    method: "POST",
  });
}

export function transitionOperationalAction(
  id: string,
  status: "in_progress" | "blocked" | "completed" | "cancelled",
  expectedVersion: number,
  summary?: string,
): Promise<OperationalAction> {
  return apiRequest(`/operations/actions/${id}/transition`, {
    body: JSON.stringify({
      expected_version: expectedVersion,
      status,
      summary: summary || undefined,
    }),
    method: "POST",
  });
}

export function reopenOperationalAction(
  id: string,
  expectedVersion: number,
  reason: string,
): Promise<OperationalAction> {
  return apiRequest(`/operations/actions/${id}/reopen`, {
    body: JSON.stringify({ expected_version: expectedVersion, reason }),
    method: "POST",
  });
}

export function addActionNote(id: string, body: string): Promise<OperationalNote> {
  return apiRequest(`/operations/actions/${id}/notes`, {
    body: JSON.stringify({ body }),
    method: "POST",
  });
}

export function addAlertNote(id: string, body: string): Promise<OperationalNote> {
  return apiRequest(`/operations/alerts/${id}/notes`, {
    body: JSON.stringify({ body }),
    method: "POST",
  });
}

export function listOperationalNotes(
  parent: { readonly actionId: string } | { readonly alertId: string },
  signal?: AbortSignal,
): Promise<readonly OperationalNote[]> {
  return apiRequest(
    `/operations/notes${queryString({
      action_id: "actionId" in parent ? parent.actionId : undefined,
      alert_id: "alertId" in parent ? parent.alertId : undefined,
      limit: 100,
    })}`,
    { signal },
  );
}

export function submitMaintenanceFeedback(payload: {
  readonly action_id?: string;
  readonly alert_id?: string;
  readonly downtime_minutes?: number;
  readonly maintenance_category?: string;
  readonly outcome: FeedbackOutcome;
  readonly replaced_component?: string;
  readonly summary: string;
}): Promise<MaintenanceFeedback> {
  return apiRequest("/operations/maintenance-feedback", {
    body: JSON.stringify(payload),
    method: "POST",
  });
}

export function listMaintenanceFeedback(
  options: {
    readonly actionId?: string;
    readonly alertId?: string;
    readonly limit?: number;
    readonly machineId?: string;
    readonly offset?: number;
    readonly outcome?: FeedbackOutcome;
    readonly signal?: AbortSignal;
  } = {},
): Promise<{
  readonly items: readonly MaintenanceFeedback[];
  readonly limit: number;
  readonly offset: number;
  readonly total: number;
}> {
  return apiRequest(
    `/operations/maintenance-feedback${queryString({
      action_id: options.actionId,
      alert_id: options.alertId,
      limit: options.limit ?? 50,
      machine_id: options.machineId,
      offset: options.offset ?? 0,
      outcome: options.outcome,
    })}`,
    { signal: options.signal },
  );
}

export function listTimeline(
  options: {
    readonly eventType?: string;
    readonly factoryId?: string;
    readonly limit?: number;
    readonly machineId?: string;
    readonly offset?: number;
    readonly signal?: AbortSignal;
  } = {},
): Promise<TimelinePage> {
  return apiRequest(
    `/operations/timeline${queryString({
      event_type: options.eventType,
      factory_id: options.factoryId,
      limit: options.limit ?? 30,
      machine_id: options.machineId,
      offset: options.offset ?? 0,
    })}`,
    { signal: options.signal },
  );
}

export function listOperationalAlerts(
  options: {
    readonly assignedUserId?: string;
    readonly factoryId?: string;
    readonly limit?: number;
    readonly machineId?: string;
    readonly offset?: number;
    readonly severity?: string;
    readonly signal?: AbortSignal;
    readonly status?: string;
  } = {},
): Promise<OperationalAlertPage> {
  return apiRequest(
    `/operations/alerts${queryString({
      assigned_user_id: options.assignedUserId,
      factory_id: options.factoryId,
      limit: options.limit ?? 25,
      machine_id: options.machineId,
      offset: options.offset ?? 0,
      severity: options.severity,
      status: options.status,
    })}`,
    { signal: options.signal },
  );
}

export function getOperationalAlert(
  id: string,
  signal?: AbortSignal,
): Promise<OperationalAlert> {
  return apiRequest(`/operations/alerts/${id}`, { signal });
}

export function transitionOperationalAlert(
  id: string,
  payload: {
    readonly assigned_user_id?: string;
    readonly expected_version: number;
    readonly note?: string;
    readonly reopen_reason?: string;
    readonly resolution_classification?: string;
    readonly resolution_summary?: string;
    readonly transition:
      "assign" | "acknowledge" | "start" | "escalate" | "resolve" | "reopen";
  },
): Promise<OperationalAlert> {
  return apiRequest(`/operations/alerts/${id}/lifecycle`, {
    body: JSON.stringify(payload),
    method: "POST",
  });
}

export function getOperationalSummary(
  signal?: AbortSignal,
): Promise<OperationalSummary> {
  return apiRequest("/operations/summary", { signal });
}

export function listOperationalAssignees(
  signal?: AbortSignal,
): Promise<readonly OperationalAssignee[]> {
  return apiRequest("/operations/assignees", { signal });
}

export function searchOperations(
  query: string,
  signal?: AbortSignal,
): Promise<{
  readonly items: readonly OperationalSearchResult[];
  readonly limit: number;
}> {
  return apiRequest(
    `/operations/search${queryString({ limit: 12, query: query.trim() })}`,
    { signal },
  );
}

export function listShifts(
  options: {
    readonly factoryId?: string;
    readonly limit?: number;
    readonly offset?: number;
    readonly signal?: AbortSignal;
    readonly status?: ShiftStatus;
  } = {},
): Promise<ShiftPage> {
  return apiRequest(
    `/operations/shifts${queryString({
      factory_id: options.factoryId,
      limit: options.limit ?? 20,
      offset: options.offset ?? 0,
      status: options.status,
    })}`,
    { signal: options.signal },
  );
}

export function getShift(id: string, signal?: AbortSignal): Promise<ShiftHandover> {
  return apiRequest(`/operations/shifts/${id}`, { signal });
}

export function startShift(
  factoryId: string,
  teamLabel?: string,
): Promise<ShiftHandover> {
  return apiRequest("/operations/shifts", {
    body: JSON.stringify({
      factory_id: factoryId,
      team_label: teamLabel || undefined,
    }),
    method: "POST",
  });
}

export function endShift(
  id: string,
  handoverNotes: string,
  unresolvedSummary?: string,
): Promise<ShiftHandover> {
  return apiRequest(`/operations/shifts/${id}/end`, {
    body: JSON.stringify({
      handover_notes: handoverNotes,
      unresolved_summary: unresolvedSummary || undefined,
    }),
    method: "POST",
  });
}

export function acknowledgeShift(
  id: string,
  acknowledgementNote?: string,
): Promise<ShiftHandover> {
  return apiRequest(`/operations/shifts/${id}/acknowledge`, {
    body: JSON.stringify({
      acknowledgement_note: acknowledgementNote || undefined,
    }),
    method: "POST",
  });
}
