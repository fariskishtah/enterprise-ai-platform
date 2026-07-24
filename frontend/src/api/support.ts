import { apiRequest } from "./client";

export type SupportCategory =
  | "technical_problem"
  | "data_import"
  | "training"
  | "predictions"
  | "alerts_and_operations"
  | "reports"
  | "account_access"
  | "other";

export type SupportStatus = "submitted" | "delivered" | "delivery_failed" | "closed";

export interface SupportRequestResult {
  readonly category: SupportCategory;
  readonly created_at: string;
  readonly current_page: string;
  readonly delivered_at: string | null;
  readonly delivery_attempts: number;
  readonly delivery_message: string;
  readonly factory_id: string | null;
  readonly id: string;
  readonly machine_id: string | null;
  readonly status: SupportStatus;
  readonly subject: string;
  readonly updated_at: string;
}

export function createSupportRequest(payload: {
  readonly category: SupportCategory;
  readonly current_page: string;
  readonly factory_id?: string;
  readonly idempotency_key: string;
  readonly machine_id?: string;
  readonly message: string;
  readonly subject: string;
}): Promise<SupportRequestResult> {
  return apiRequest("/support/requests", {
    body: JSON.stringify(payload),
    method: "POST",
  });
}
