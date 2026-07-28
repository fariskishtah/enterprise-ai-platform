import { apiRequest } from "./client";

export interface BillingPlan {
  readonly code: string;
  readonly currency: "EGP";
  readonly description: string;
  readonly entitlements: Readonly<Record<string, number | boolean>>;
  readonly monthly_price_minor: number;
  readonly name: string;
}

export interface BillingDetails {
  readonly city: string;
  readonly country: string;
  readonly first_name: string;
  readonly last_name: string;
  readonly phone_number: string;
  readonly street: string;
}

export interface HostedCheckout {
  readonly amount_minor: number;
  readonly checkout_url: string;
  readonly currency: "EGP";
  readonly failure_url: string;
  readonly payment_id: string;
  readonly plan_code: string;
  readonly provider: "paymob";
  readonly provider_checkout_id: string;
  readonly reused: boolean;
  readonly status: string;
}

export interface PaymentStatus {
  readonly amount_minor: number;
  readonly currency: "EGP";
  readonly failure_code: string | null;
  readonly payment_id: string;
  readonly plan_code: string | null;
  readonly status: string;
}

export function listBillingPlans(
  signal?: AbortSignal,
): Promise<{ readonly items: readonly BillingPlan[] }> {
  return apiRequest("/billing/plans", { signal }, { authenticated: false });
}

export function createHostedCheckout(
  planCode: string,
  billingDetails: BillingDetails,
  idempotencyKey: string,
): Promise<HostedCheckout> {
  return apiRequest<HostedCheckout>("/billing/checkouts", {
    body: JSON.stringify({
      billing_details: billingDetails,
      plan_code: planCode,
    }),
    headers: { "Idempotency-Key": idempotencyKey },
    method: "POST",
  });
}

export function getPaymentStatus(
  paymentId: string,
  signal?: AbortSignal,
): Promise<PaymentStatus> {
  return apiRequest<PaymentStatus>(`/billing/payments/${paymentId}`, { signal });
}

export function cancelHostedCheckout(paymentId: string): Promise<PaymentStatus> {
  return apiRequest<PaymentStatus>(`/billing/payments/${paymentId}/cancel`, {
    method: "POST",
  });
}
