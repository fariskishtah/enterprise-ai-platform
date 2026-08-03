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
  readonly purpose: "initial" | "renewal" | "plan_change" | "reactivation";
  readonly checkout_expires_at: string | null;
  readonly commercial_model: CommercialBillingModel;
  readonly reused: boolean;
  readonly status: string;
  readonly subscription_id: string;
}

export interface PaymentStatus {
  readonly amount_minor: number;
  readonly created_at: string;
  readonly currency: "EGP";
  readonly failure_code: string | null;
  readonly payment_id: string;
  readonly plan_code: string | null;
  readonly provider: string;
  readonly provider_checkout_id: string | null;
  readonly provider_occurred_at: string | null;
  readonly provider_payment_id: string | null;
  readonly purpose: string;
  readonly status: string;
  readonly updated_at: string;
  readonly checkout_expires_at: string | null;
  readonly checkout_intent_status:
    "open" | "superseded" | "completed" | "failed" | "expired" | "cancelled";
  readonly commercial_model: CommercialBillingModel;
  readonly provider_decision:
    | "pending"
    | "authorized_not_captured"
    | "succeeded_eligible"
    | "failed"
    | "cancelled"
    | "expired"
    | "refunded"
    | "reversed"
    | "under_review"
    | "quarantined";
}

export type CommercialBillingModel =
  "prepaid_manual_renewal" | "provider_recurring_subscription";

export interface BillingPlanList {
  readonly items: readonly BillingPlan[];
  readonly commercial_model: CommercialBillingModel;
}

export interface Subscription {
  readonly allowed_actions: readonly string[];
  readonly cancel_at_period_end: boolean;
  readonly current_period_end: string | null;
  readonly current_period_start: string | null;
  readonly ended_at: string | null;
  readonly grace_period_ends_at: string | null;
  readonly pending_plan_code: string | null;
  readonly plan_code: string;
  readonly status: string;
  readonly subscription_id: string;
  readonly suspended_at: string | null;
  readonly version: number;
}

export interface EntitlementItem {
  readonly enabled: boolean | null;
  readonly key: string;
  readonly limit: number | null;
  readonly over_limit: boolean;
  readonly period_end: string | null;
  readonly period_start: string | null;
  readonly remaining: number | null;
  readonly source: string;
  readonly used: number | null;
}

export interface EntitlementSnapshot {
  readonly access_mode: string;
  readonly items: readonly EntitlementItem[];
  readonly plan_code: string | null;
  readonly recommended_plan: string | null;
  readonly subscription_status: string | null;
}

export interface InvoiceReference {
  readonly amount_minor: number;
  readonly currency: "EGP";
  readonly invoice_id: string;
  readonly issued_at: string | null;
  readonly payment_id: string | null;
  readonly provider: string;
  readonly provider_invoice_id: string;
  readonly receipt_url: string | null;
  readonly status: string;
}

export interface BillingAuditEvent {
  readonly action: string;
  readonly actor_user_id: string | null;
  readonly created_at: string;
  readonly event_id: string;
  readonly result: string;
  readonly safe_metadata: Readonly<Record<string, unknown>>;
}

export interface BillingProviderEvent {
  readonly attempts: number;
  readonly event_id: string;
  readonly event_type: string;
  readonly last_error: string | null;
  readonly processed_at: string | null;
  readonly provider: string;
  readonly provider_event_id: string;
  readonly received_at: string;
  readonly status: string;
}

export interface PageResponse<T> {
  readonly items: readonly T[];
  readonly page: number;
  readonly page_size: number;
  readonly total: number;
}

interface CheckoutPayload {
  readonly billing_details: BillingDetails;
  readonly plan_code: string;
}

export function listBillingPlans(signal?: AbortSignal): Promise<BillingPlanList> {
  return apiRequest("/billing/plans", { signal }, { authenticated: false });
}

function checkoutRequest(
  path: string,
  payload: CheckoutPayload,
  idempotencyKey: string,
): Promise<HostedCheckout> {
  return apiRequest<HostedCheckout>(path, {
    body: JSON.stringify(payload),
    headers: { "Idempotency-Key": idempotencyKey },
    method: "POST",
  });
}

export function createHostedCheckout(
  planCode: string,
  billingDetails: BillingDetails,
  idempotencyKey: string,
): Promise<HostedCheckout> {
  return checkoutRequest(
    "/billing/checkouts",
    { billing_details: billingDetails, plan_code: planCode },
    idempotencyKey,
  );
}

export function changeSubscriptionPlan(
  direction: "upgrade" | "downgrade",
  planCode: string,
  billingDetails: BillingDetails,
  idempotencyKey: string,
): Promise<HostedCheckout> {
  return checkoutRequest(
    `/billing/subscription/${direction}`,
    { billing_details: billingDetails, plan_code: planCode },
    idempotencyKey,
  );
}

export function getSubscription(signal?: AbortSignal): Promise<{
  readonly item: Subscription | null;
}> {
  return apiRequest("/billing/subscription", { signal });
}

export function getEntitlements(signal?: AbortSignal): Promise<EntitlementSnapshot> {
  return apiRequest("/billing/entitlements", { signal });
}

export function listPayments(
  signal?: AbortSignal,
): Promise<PageResponse<PaymentStatus>> {
  return apiRequest("/billing/history/payments?page=1&page_size=20", { signal });
}

export function listInvoices(
  signal?: AbortSignal,
): Promise<PageResponse<InvoiceReference>> {
  return apiRequest("/billing/history/invoices?page=1&page_size=20", { signal });
}

export function listBillingAuditEvents(
  signal?: AbortSignal,
): Promise<PageResponse<BillingAuditEvent>> {
  return apiRequest("/billing/admin/events?page=1&page_size=20", { signal });
}

export function listBillingProviderEvents(
  signal?: AbortSignal,
): Promise<PageResponse<BillingProviderEvent>> {
  return apiRequest("/billing/admin/provider-events?page=1&page_size=20", { signal });
}

export function getPaymentStatus(
  paymentId: string,
  signal?: AbortSignal,
): Promise<PaymentStatus> {
  return apiRequest<PaymentStatus>(`/billing/payments/${paymentId}`, { signal });
}

export function resolveBillingReturn(
  state: string,
  signal?: AbortSignal,
): Promise<PaymentStatus> {
  return apiRequest<PaymentStatus>("/billing/returns/resolve", {
    body: JSON.stringify({ state }),
    method: "POST",
    signal,
  });
}

export function cancelHostedCheckout(paymentId: string): Promise<PaymentStatus> {
  return apiRequest<PaymentStatus>(`/billing/payments/${paymentId}/cancel`, {
    method: "POST",
  });
}

export function cancelSubscription(
  mode: "period_end" | "immediate" = "period_end",
): Promise<Subscription> {
  return apiRequest<Subscription>("/billing/subscription/cancel", {
    body: JSON.stringify({ mode }),
    method: "POST",
  });
}

export function reactivateSubscription(): Promise<Subscription> {
  return apiRequest<Subscription>("/billing/subscription/reactivate", {
    method: "POST",
  });
}
