import { useCallback, useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import {
  cancelSubscription,
  getEntitlements,
  getSubscription,
  listBillingAuditEvents,
  listBillingPlans,
  listBillingProviderEvents,
  listInvoices,
  listPayments,
  reactivateSubscription,
  type BillingPlan,
  type BillingAuditEvent,
  type BillingProviderEvent,
  type EntitlementSnapshot,
  type InvoiceReference,
  type PaymentStatus,
  type Subscription,
} from "../../api/billing";
import { isRequestCancelled } from "../../api/client";
import {
  InlineError,
  LoadingSkeleton,
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { PageHeader } from "../../components/ui/PageHeader";
import {
  BillingStatus,
  billingPanelClassName,
  entitlementLabels,
  formatBillingDate,
  formatMoney,
} from "./BillingUi";

interface BillingWorkspace {
  readonly auditEvents: readonly BillingAuditEvent[];
  readonly entitlements: EntitlementSnapshot;
  readonly invoices: readonly InvoiceReference[];
  readonly payments: readonly PaymentStatus[];
  readonly plans: readonly BillingPlan[];
  readonly providerEvents: readonly BillingProviderEvent[];
  readonly subscription: Subscription | null;
}

function LifecycleBanner({
  subscription,
}: {
  readonly subscription: Subscription;
}): ReactElement | null {
  let title: string | null = null;
  let detail = "";
  let tone = "border-blue-200 bg-blue-50 text-blue-950";
  if (subscription.status === "past_due") {
    title = "Payment past due";
    detail = subscription.grace_period_ends_at
      ? `Your workspace remains available during the grace period ending ${formatBillingDate(subscription.grace_period_ends_at)}.`
      : "Update payment by retrying checkout before access is restricted.";
    tone = "border-amber-300 bg-amber-50 text-amber-950";
  } else if (subscription.status === "suspended") {
    title = "Workspace is read-only";
    detail =
      "Your subscription is suspended. Existing resources remain visible, but mutations require reactivation.";
    tone = "border-red-300 bg-red-50 text-red-950";
  } else if (["cancelled", "expired"].includes(subscription.status)) {
    title = "Subscription inactive";
    detail = "Choose a plan and complete verified checkout to restore paid access.";
    tone = "border-neutral-300 bg-neutral-100 text-neutral-950";
  } else if (subscription.status === "incomplete") {
    title = "Checkout not completed";
    detail =
      "Your plan will activate only after the payment provider sends a verified success event.";
  } else if (subscription.cancel_at_period_end) {
    title = "Cancellation scheduled";
    detail = `Access continues until ${formatBillingDate(subscription.current_period_end)}. You can reactivate before then.`;
    tone = "border-amber-300 bg-amber-50 text-amber-950";
  } else if (subscription.pending_plan_code !== null) {
    title = "Plan change pending";
    detail = `Your ${subscription.pending_plan_code} plan starts only after verified payment succeeds.`;
  }
  return title === null ? null : (
    <div className={`mt-6 rounded-lg border p-4 ${tone}`} role="status">
      <p className="font-semibold">{title}</p>
      <p className="mt-1 text-sm">{detail}</p>
    </div>
  );
}

function UsageCard({
  item,
}: {
  readonly item: EntitlementSnapshot["items"][number];
}): ReactElement {
  const ratio =
    item.limit !== null && item.used !== null && item.limit > 0
      ? Math.min(100, Math.round((item.used / item.limit) * 100))
      : 0;
  const description =
    item.limit !== null
      ? `${(item.used ?? 0).toLocaleString()} of ${item.limit.toLocaleString()}`
      : item.enabled === true
        ? "Included"
        : item.enabled === false
          ? "Not included"
          : "Unlimited";
  return (
    <li className="rounded-lg border border-border bg-elevated p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-semibold text-foreground">
          {entitlementLabels[item.key] ?? item.key.replaceAll("_", " ")}
        </p>
        {item.over_limit ? <BillingStatus status="past_due" /> : null}
      </div>
      <p className="mt-2 text-2xl font-semibold text-foreground">{description}</p>
      {item.limit !== null && item.used !== null ? (
        <div
          aria-label={`${entitlementLabels[item.key] ?? item.key} usage ${ratio}%`}
          className="mt-3 h-2 overflow-hidden rounded-full bg-neutral-200"
          role="progressbar"
          aria-valuemax={100}
          aria-valuemin={0}
          aria-valuenow={ratio}
        >
          <div
            className={`h-full rounded-full ${item.over_limit ? "bg-red-600" : ratio >= 80 ? "bg-amber-500" : "bg-purple-700"}`}
            style={{ width: `${ratio}%` }}
          />
        </div>
      ) : null}
      <p className="mt-2 text-xs text-muted-foreground">
        {item.period_end
          ? `Resets ${formatBillingDate(item.period_end)}`
          : `Source: ${item.source}`}
      </p>
    </li>
  );
}

export function BillingOverviewPage(): ReactElement {
  const [workspace, setWorkspace] = useState<BillingWorkspace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmCancellation, setConfirmCancellation] = useState(false);
  const [revision, setRevision] = useState(0);

  const reload = useCallback(() => {
    setError(null);
    setWorkspace(null);
    setRevision((value) => value + 1);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getSubscription(controller.signal),
      getEntitlements(controller.signal),
      listPayments(controller.signal),
      listInvoices(controller.signal),
      listBillingPlans(controller.signal),
      listBillingAuditEvents(controller.signal),
      listBillingProviderEvents(controller.signal),
    ])
      .then(
        ([
          subscription,
          entitlements,
          payments,
          invoices,
          plans,
          auditEvents,
          providerEvents,
        ]) =>
          setWorkspace({
            auditEvents: auditEvents.items,
            entitlements,
            invoices: invoices.items,
            payments: payments.items,
            plans: plans.items,
            providerEvents: providerEvents.items,
            subscription: subscription.item,
          }),
      )
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal)) {
          setError(
            caught instanceof Error
              ? caught.message
              : "Billing is temporarily unavailable.",
          );
        }
      });
    return () => controller.abort();
  }, [revision]);

  const mutate = (operation: () => Promise<Subscription>): void => {
    setBusy(true);
    setError(null);
    void operation()
      .then(() => {
        setConfirmCancellation(false);
        reload();
      })
      .catch((caught: unknown) =>
        setError(
          caught instanceof Error
            ? caught.message
            : "The subscription could not be updated.",
        ),
      )
      .finally(() => setBusy(false));
  };

  return (
    <section aria-labelledby="billing-heading">
      <PageHeader
        eyebrow="Workspace administration"
        headingId="billing-heading"
        title="Billing & subscription"
        description="Manage the current plan, verified payment lifecycle, limits, invoices, and workspace usage."
      />
      {error ? (
        <div className="mt-6">
          <InlineError message={error} onRetry={reload} />
        </div>
      ) : null}
      {workspace === null && error === null ? (
        <div className="mt-6">
          <LoadingSkeleton label="Loading billing workspace" />
        </div>
      ) : null}
      {workspace !== null ? (
        <>
          {workspace.subscription ? (
            <LifecycleBanner subscription={workspace.subscription} />
          ) : (
            <div
              className="mt-6 rounded-lg border border-blue-200 bg-blue-50 p-4 text-blue-950"
              role="status"
            >
              <p className="font-semibold">No subscription yet</p>
              <p className="mt-1 text-sm">
                Choose a plan below. Access activates only after verified payment
                succeeds.
              </p>
            </div>
          )}
          <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(20rem,0.6fr)]">
            <section
              className={billingPanelClassName}
              aria-labelledby="current-plan-heading"
            >
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-eyebrow">
                    Current plan
                  </p>
                  <h3
                    className="mt-2 text-2xl font-semibold capitalize text-foreground"
                    id="current-plan-heading"
                  >
                    {workspace.subscription?.plan_code ?? "No active plan"}
                  </h3>
                  <div className="mt-3">
                    <BillingStatus
                      status={workspace.subscription?.status ?? "inactive"}
                    />
                  </div>
                </div>
                {workspace.subscription?.current_period_end ? (
                  <div className="text-right text-sm text-muted-foreground">
                    <p>Current period ends</p>
                    <p className="mt-1 font-semibold text-foreground">
                      {formatBillingDate(workspace.subscription.current_period_end)}
                    </p>
                  </div>
                ) : null}
              </div>
              {workspace.subscription ? (
                <dl className="mt-6 grid gap-3 border-t border-border pt-5 text-sm sm:grid-cols-2">
                  <div>
                    <dt className="text-muted-foreground">Subscription ID</dt>
                    <dd className="mt-1 break-all font-medium text-foreground">
                      {workspace.subscription.subscription_id}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Version</dt>
                    <dd className="mt-1 font-medium text-foreground">
                      {workspace.subscription.version}
                    </dd>
                  </div>
                  {workspace.subscription.pending_plan_code ? (
                    <div>
                      <dt className="text-muted-foreground">Pending plan</dt>
                      <dd className="mt-1 font-medium capitalize text-foreground">
                        {workspace.subscription.pending_plan_code}
                      </dd>
                    </div>
                  ) : null}
                  {workspace.subscription.grace_period_ends_at ? (
                    <div>
                      <dt className="text-muted-foreground">Grace period ends</dt>
                      <dd className="mt-1 font-medium text-foreground">
                        {formatBillingDate(workspace.subscription.grace_period_ends_at)}
                      </dd>
                    </div>
                  ) : null}
                </dl>
              ) : null}
              {workspace.subscription ? (
                <div className="mt-5 flex flex-wrap gap-3">
                  {workspace.subscription.allowed_actions.includes("reactivate") ? (
                    <button
                      className={primaryButtonClassName}
                      disabled={busy}
                      onClick={() => mutate(reactivateSubscription)}
                      type="button"
                    >
                      Reactivate subscription
                    </button>
                  ) : null}
                  {workspace.subscription.allowed_actions.includes("cancel") &&
                  !workspace.subscription.cancel_at_period_end ? (
                    <button
                      className={secondaryButtonClassName}
                      disabled={busy}
                      onClick={() => setConfirmCancellation(true)}
                      type="button"
                    >
                      Schedule cancellation
                    </button>
                  ) : null}
                </div>
              ) : null}
              {confirmCancellation ? (
                <div
                  className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950"
                  role="alertdialog"
                  aria-labelledby="cancel-title"
                >
                  <p className="font-semibold" id="cancel-title">
                    Cancel at the end of this billing period?
                  </p>
                  <p className="mt-1">
                    No resources are deleted. Paid access continues through the current
                    period.
                  </p>
                  <div className="mt-4 flex gap-3">
                    <button
                      className={primaryButtonClassName}
                      disabled={busy}
                      onClick={() => mutate(() => cancelSubscription("period_end"))}
                      type="button"
                    >
                      Confirm cancellation
                    </button>
                    <button
                      className={secondaryButtonClassName}
                      disabled={busy}
                      onClick={() => setConfirmCancellation(false)}
                      type="button"
                    >
                      Keep subscription
                    </button>
                  </div>
                </div>
              ) : null}
            </section>
            <section className={billingPanelClassName} aria-labelledby="access-heading">
              <p className="text-xs font-semibold uppercase tracking-wider text-eyebrow">
                Effective access
              </p>
              <h3
                className="mt-2 text-xl font-semibold capitalize text-foreground"
                id="access-heading"
              >
                {workspace.entitlements.access_mode.replaceAll("_", " ")}
              </h3>
              <p className="mt-2 text-sm text-muted-foreground">
                Calculated by the server from subscription state, plan limits, current
                usage, and active overrides.
              </p>
              {workspace.entitlements.recommended_plan ? (
                <Link
                  className={`${primaryButtonClassName} mt-5 inline-flex`}
                  to={`/settings/billing/checkout/${workspace.entitlements.recommended_plan}`}
                >
                  Review recommended plan
                </Link>
              ) : null}
            </section>
          </div>

          <section
            className={`${billingPanelClassName} mt-6`}
            aria-labelledby="usage-heading"
          >
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-eyebrow">
                Entitlements
              </p>
              <h3
                className="mt-2 text-xl font-semibold text-foreground"
                id="usage-heading"
              >
                Usage & limits
              </h3>
              <p className="mt-1 text-sm text-muted-foreground">
                Live tenant usage measured against effective plan limits.
              </p>
            </div>
            <ul className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {workspace.entitlements.items.map((item) => (
                <UsageCard item={item} key={item.key} />
              ))}
            </ul>
          </section>

          <section
            className={`${billingPanelClassName} mt-6`}
            aria-labelledby="plans-heading"
          >
            <h3 className="text-xl font-semibold text-foreground" id="plans-heading">
              Change plan
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Checkout is hosted by Paymob. A redirect result never changes your plan
              until the backend verifies the provider event.
            </p>
            <div className="mt-5 grid gap-4 md:grid-cols-3">
              {workspace.plans.map((plan) => {
                const current = plan.code === workspace.subscription?.plan_code;
                return (
                  <article
                    className="rounded-lg border border-border bg-elevated p-4"
                    key={plan.code}
                  >
                    <h4 className="font-semibold text-foreground">{plan.name}</h4>
                    <p className="mt-2 text-xl font-semibold text-foreground">
                      {formatMoney(plan.monthly_price_minor)}
                      <span className="text-xs font-normal text-muted-foreground">
                        {" "}
                        / month
                      </span>
                    </p>
                    {current ? (
                      <p className="mt-4 text-sm font-semibold text-link">
                        Current plan
                      </p>
                    ) : (
                      <Link
                        className={`${secondaryButtonClassName} mt-4 inline-flex`}
                        to={`/settings/billing/checkout/${plan.code}`}
                      >
                        {workspace.subscription
                          ? `Change to ${plan.name}`
                          : `Choose ${plan.name}`}
                      </Link>
                    )}
                  </article>
                );
              })}
            </div>
          </section>

          <div className="mt-6 grid gap-6 xl:grid-cols-2">
            <HistoryTable payments={workspace.payments} />
            <InvoiceTable invoices={workspace.invoices} />
          </div>
          <div className="mt-6 grid gap-6 xl:grid-cols-2">
            <BillingAuditTable events={workspace.auditEvents} />
            <ProviderEventTable events={workspace.providerEvents} />
          </div>
        </>
      ) : null}
    </section>
  );
}

function BillingAuditTable({
  events,
}: {
  readonly events: readonly BillingAuditEvent[];
}): ReactElement {
  return (
    <section className={billingPanelClassName} aria-labelledby="billing-events-heading">
      <h3 className="text-xl font-semibold text-foreground" id="billing-events-heading">
        Billing activity
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Tenant-scoped administrative lifecycle audit trail.
      </p>
      {events.length === 0 ? (
        <p className="mt-5 text-sm text-muted-foreground">
          No billing activity has been recorded.
        </p>
      ) : (
        <ul className="mt-5 divide-y divide-border">
          {events.map((event) => (
            <li
              className="flex items-start justify-between gap-4 py-4 first:pt-0 last:pb-0"
              key={event.event_id}
            >
              <div>
                <p className="font-medium text-foreground">
                  {event.action.replaceAll("_", " ")}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {formatBillingDate(event.created_at)}
                </p>
              </div>
              <BillingStatus status={event.result} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ProviderEventTable({
  events,
}: {
  readonly events: readonly BillingProviderEvent[];
}): ReactElement {
  return (
    <section
      className={billingPanelClassName}
      aria-labelledby="provider-events-heading"
    >
      <h3
        className="text-xl font-semibold text-foreground"
        id="provider-events-heading"
      >
        Provider event inspection
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Authenticated Paymob callbacks and their durable processing state.
      </p>
      {events.length === 0 ? (
        <p className="mt-5 text-sm text-muted-foreground">
          No provider events have been received.
        </p>
      ) : (
        <ul className="mt-5 divide-y divide-border">
          {events.map((event) => (
            <li className="py-4 first:pt-0 last:pb-0" key={event.event_id}>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="font-medium text-foreground">
                    {event.event_type.replaceAll("_", " ")}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {event.provider} · {event.provider_event_id} · {event.attempts}{" "}
                    attempt{event.attempts === 1 ? "" : "s"}
                  </p>
                </div>
                <BillingStatus status={event.status} />
              </div>
              {event.last_error ? (
                <p className="mt-2 text-sm text-red-700">{event.last_error}</p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function HistoryTable({
  payments,
}: {
  readonly payments: readonly PaymentStatus[];
}): ReactElement {
  return (
    <section
      className={billingPanelClassName}
      aria-labelledby="payment-history-heading"
    >
      <h3
        className="text-xl font-semibold text-foreground"
        id="payment-history-heading"
      >
        Payment history
      </h3>
      {payments.length === 0 ? (
        <p className="mt-5 text-sm text-muted-foreground">
          No payments have been recorded.
        </p>
      ) : (
        <div
          aria-label="Scrollable payment history"
          className="mt-5 overflow-x-auto"
          role="region"
          tabIndex={0}
        >
          <table className="w-full min-w-[34rem] text-left text-sm">
            <thead className="border-b border-border text-xs uppercase text-muted-foreground">
              <tr>
                <th className="pb-3 pr-4">Date</th>
                <th className="pb-3 pr-4">Plan</th>
                <th className="pb-3 pr-4">Amount</th>
                <th className="pb-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {payments.map((payment) => (
                <tr
                  className="border-b border-border last:border-0"
                  key={payment.payment_id}
                >
                  <td className="py-4 pr-4 text-muted-foreground">
                    {formatBillingDate(payment.created_at)}
                  </td>
                  <td className="py-4 pr-4 capitalize text-foreground">
                    {payment.plan_code ?? "—"}
                  </td>
                  <td className="py-4 pr-4 font-medium text-foreground">
                    {formatMoney(payment.amount_minor, payment.currency)}
                  </td>
                  <td className="py-4">
                    <BillingStatus status={payment.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function InvoiceTable({
  invoices,
}: {
  readonly invoices: readonly InvoiceReference[];
}): ReactElement {
  return (
    <section
      className={billingPanelClassName}
      aria-labelledby="invoice-history-heading"
    >
      <h3
        className="text-xl font-semibold text-foreground"
        id="invoice-history-heading"
      >
        Invoices & receipts
      </h3>
      {invoices.length === 0 ? (
        <p className="mt-5 text-sm text-muted-foreground">
          No invoices have been issued.
        </p>
      ) : (
        <div
          aria-label="Scrollable invoice history"
          className="mt-5 overflow-x-auto"
          role="region"
          tabIndex={0}
        >
          <table className="w-full min-w-[32rem] text-left text-sm">
            <thead className="border-b border-border text-xs uppercase text-muted-foreground">
              <tr>
                <th className="pb-3 pr-4">Issued</th>
                <th className="pb-3 pr-4">Reference</th>
                <th className="pb-3 pr-4">Amount</th>
                <th className="pb-3">Receipt</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((invoice) => (
                <tr
                  className="border-b border-border last:border-0"
                  key={invoice.invoice_id}
                >
                  <td className="py-4 pr-4 text-muted-foreground">
                    {formatBillingDate(invoice.issued_at)}
                  </td>
                  <td className="py-4 pr-4 font-medium text-foreground">
                    {invoice.provider_invoice_id}
                  </td>
                  <td className="py-4 pr-4 text-foreground">
                    {formatMoney(invoice.amount_minor, invoice.currency)}
                  </td>
                  <td className="py-4">
                    {invoice.receipt_url ? (
                      <a
                        className="font-semibold text-purple-700 hover:underline"
                        href={invoice.receipt_url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        Open receipt
                      </a>
                    ) : (
                      <span className="text-muted-foreground">Unavailable</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
