import { apiRequest } from "./client";

export interface BillingPlan {
  readonly code: string;
  readonly currency: "EGP";
  readonly description: string;
  readonly entitlements: Readonly<Record<string, number | boolean>>;
  readonly monthly_price_minor: number;
  readonly name: string;
}

export function listBillingPlans(
  signal?: AbortSignal,
): Promise<{ readonly items: readonly BillingPlan[] }> {
  return apiRequest("/billing/plans", { signal }, { authenticated: false });
}
