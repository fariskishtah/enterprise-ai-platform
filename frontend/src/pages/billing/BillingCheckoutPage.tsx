import { useEffect, useRef, useState, type FormEvent, type ReactElement } from "react";
import { Link, useParams } from "react-router-dom";

import {
  changeSubscriptionPlan,
  createHostedCheckout,
  getSubscription,
  listBillingPlans,
  type BillingPlan,
  type Subscription,
} from "../../api/billing";
import { useAuth } from "../../auth/useAuth";
import {
  InlineError,
  LoadingSkeleton,
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { inputClassName } from "../../components/intelligence/IntelligenceUi";
import { PageHeader } from "../../components/ui/PageHeader";
import { billingPanelClassName, formatMoney } from "./BillingUi";

function safeCheckoutRedirect(value: string): void {
  const target = new URL(value, window.location.origin);
  const providerHosts = new Set([
    "accept.paymob.com",
    "ksa.paymob.com",
    "oman.paymob.com",
    "uae.paymob.com",
  ]);
  const sameOrigin = target.origin === window.location.origin;
  if (
    (!sameOrigin && target.protocol !== "https:") ||
    (!sameOrigin && !providerHosts.has(target.hostname.toLowerCase()))
  ) {
    throw new Error("The payment provider returned an invalid checkout URL.");
  }
  window.location.assign(target.href);
}

export function BillingCheckoutPage(): ReactElement {
  const { planCode = "" } = useParams();
  const { user } = useAuth();
  const [plan, setPlan] = useState<BillingPlan | null>(null);
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const idempotencyKey = useRef(`web-${crypto.randomUUID()}`);
  const submissionStarted = useRef(false);

  useEffect(() => {
    Promise.all([listBillingPlans(), getSubscription()])
      .then(([plans, current]) => {
        const selected = plans.items.find((item) => item.code === planCode) ?? null;
        setPlan(selected);
        setSubscription(current.item);
        if (selected === null) setError("That billing plan is unavailable.");
      })
      .catch((caught: unknown) =>
        setError(caught instanceof Error ? caught.message : "Checkout is unavailable."),
      )
      .finally(() => setLoading(false));
  }, [planCode]);

  const submit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (plan === null || submissionStarted.current) return;
    submissionStarted.current = true;
    const data = new FormData(event.currentTarget);
    const billingDetails = {
      city: String(data.get("city")),
      country: "EG",
      first_name: String(data.get("firstName")),
      last_name: String(data.get("lastName")),
      phone_number: String(data.get("phone")),
      street: String(data.get("street")),
    };
    const currentPlan = subscription === null ? null : plan;
    const request =
      subscription === null ||
      ["cancelled", "expired", "suspended", "incomplete"].includes(subscription.status)
        ? createHostedCheckout(plan.code, billingDetails, idempotencyKey.current)
        : (() => {
            const knownCurrent = currentPlan === null ? null : subscription.plan_code;
            return listBillingPlans().then(({ items }) => {
              const oldPlan = items.find((item) => item.code === knownCurrent);
              const direction =
                oldPlan !== undefined &&
                plan.monthly_price_minor < oldPlan.monthly_price_minor
                  ? "downgrade"
                  : "upgrade";
              return changeSubscriptionPlan(
                direction,
                plan.code,
                billingDetails,
                idempotencyKey.current,
              );
            });
          })();
    setBusy(true);
    setError(null);
    void request
      .then((checkout) => safeCheckoutRedirect(checkout.checkout_url))
      .catch((caught: unknown) => {
        submissionStarted.current = false;
        setError(
          caught instanceof Error ? caught.message : "Checkout could not be created.",
        );
      })
      .finally(() => setBusy(false));
  };

  const nameParts = (user?.full_name ?? "").trim().split(/\s+/);
  return (
    <section aria-labelledby="checkout-heading">
      <PageHeader
        eyebrow="Secure hosted payment"
        headingId="checkout-heading"
        title="Complete checkout"
        description="Billing details are sent to the backend to create a Paymob-hosted checkout. Card data never enters this application."
      />
      <Link
        className={`${secondaryButtonClassName} mt-6 inline-flex`}
        to="/settings/billing"
      >
        Back to billing
      </Link>
      {error ? (
        <div className="mt-6">
          <InlineError message={error} onRetry={() => window.location.reload()} />
        </div>
      ) : null}
      {loading ? (
        <div className="mt-6">
          <LoadingSkeleton label="Loading checkout" />
        </div>
      ) : null}
      {plan ? (
        <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <form className={billingPanelClassName} onSubmit={submit}>
            <h3 className="text-xl font-semibold text-foreground">Billing contact</h3>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <label className="text-sm font-medium text-foreground">
                First name
                <input
                  className={inputClassName}
                  defaultValue={nameParts[0] ?? ""}
                  name="firstName"
                  required
                />
              </label>
              <label className="text-sm font-medium text-foreground">
                Last name
                <input
                  className={inputClassName}
                  defaultValue={nameParts.slice(1).join(" ")}
                  name="lastName"
                  required
                />
              </label>
              <label className="text-sm font-medium text-foreground">
                Phone number
                <input
                  className={inputClassName}
                  name="phone"
                  pattern="\+[1-9][0-9]{7,14}"
                  placeholder="+201001234567"
                  required
                  type="tel"
                />
              </label>
              <label className="text-sm font-medium text-foreground">
                City
                <input className={inputClassName} name="city" required />
              </label>
              <label className="text-sm font-medium text-foreground sm:col-span-2">
                Street address
                <input className={inputClassName} name="street" required />
              </label>
            </div>
            <div
              className="mt-6 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950"
              role="note"
            >
              After Paymob redirects you back, this application checks the payment
              directly with the backend. Redirect query parameters are never treated as
              proof of payment.
            </div>
            <button
              className={`${primaryButtonClassName} mt-6`}
              disabled={busy}
              type="submit"
            >
              {busy
                ? "Opening Paymob…"
                : `Continue to Paymob · ${formatMoney(plan.monthly_price_minor)}`}
            </button>
          </form>
          <aside className={billingPanelClassName} aria-labelledby="order-heading">
            <p className="text-xs font-semibold uppercase tracking-wider text-eyebrow">
              Prepaid access period
            </p>
            <h3
              className="mt-2 text-2xl font-semibold text-foreground"
              id="order-heading"
            >
              {plan.name}
            </h3>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              {plan.description}
            </p>
            <p className="mt-6 border-t border-border pt-5 text-3xl font-semibold text-foreground">
              {formatMoney(plan.monthly_price_minor)}
              <span className="mt-1 block text-sm font-normal text-muted-foreground">
                One access period
              </span>
            </p>
            <p className="mt-3 text-xs text-muted-foreground">
              One payment provides one fixed access period. Renewal requires a new
              checkout; FactoryMind does not schedule automatic collection.
            </p>
          </aside>
        </div>
      ) : null}
    </section>
  );
}
