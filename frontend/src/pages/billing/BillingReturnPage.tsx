import { useCallback, useEffect, useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  cancelHostedCheckout,
  getPaymentStatus,
  type PaymentStatus,
} from "../../api/billing";
import { isRequestCancelled } from "../../api/client";
import {
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { BillingStatus, billingPanelClassName, formatMoney } from "./BillingUi";

const processingStatuses = new Set(["creating", "pending"]);

function resultCopy(payment: PaymentStatus): {
  readonly detail: string;
  readonly title: string;
} {
  if (payment.status === "succeeded")
    return {
      title: "Payment verified",
      detail:
        "The backend verified the provider event. Your subscription state has been refreshed.",
    };
  if (payment.status === "failed" || payment.status === "provider_error")
    return {
      title: "Payment was not completed",
      detail: "No paid access was granted. You can safely retry with the same plan.",
    };
  if (payment.status === "cancelled")
    return {
      title: "Checkout cancelled",
      detail: "The checkout was abandoned and no paid access was granted.",
    };
  if (payment.status === "refunded")
    return {
      title: "Payment refunded",
      detail:
        "The provider reported a refund. Your current subscription state is available in billing.",
    };
  if (payment.status === "reversed")
    return {
      title: "Payment reversed",
      detail:
        "The provider reversed this payment. Review the resulting subscription state in billing.",
    };
  return {
    title: "Confirming payment",
    detail:
      "We are waiting for a verified provider event. This page refreshes automatically; no redirect value is accepted as proof of payment.",
  };
}

export function BillingReturnPage(): ReactElement {
  const [parameters] = useSearchParams();
  const paymentId = parameters.get("payment_id");
  const [payment, setPayment] = useState<PaymentStatus | null>(null);
  const [error, setError] = useState<string | null>(
    paymentId === null ? "The return URL is missing its payment reference." : null,
  );
  const [poll, setPoll] = useState(0);
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(() => setPoll((value) => value + 1), []);

  useEffect(() => {
    if (paymentId === null) return;
    const controller = new AbortController();
    let nextPoll: number | null = null;
    getPaymentStatus(paymentId, controller.signal)
      .then((value) => {
        setPayment(value);
        setError(null);
        if (processingStatuses.has(value.status)) {
          nextPoll = window.setTimeout(refresh, 2000);
        }
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal))
          setError(
            caught instanceof Error ? caught.message : "Payment status is unavailable.",
          );
      });
    return () => {
      controller.abort();
      if (nextPoll !== null) window.clearTimeout(nextPoll);
    };
  }, [paymentId, poll, refresh]);

  const copy = payment ? resultCopy(payment) : null;
  return (
    <section
      className="mx-auto max-w-2xl py-8"
      aria-labelledby="payment-result-heading"
    >
      <div className={`${billingPanelClassName} text-center`}>
        {payment === null && error === null ? (
          <div
            aria-label="Checking payment status"
            className="mx-auto h-12 w-12 animate-spin rounded-full border-4 border-neutral-200 border-t-purple-700"
            role="status"
          />
        ) : null}
        {payment ? (
          <div className="flex justify-center">
            <BillingStatus status={payment.status} />
          </div>
        ) : null}
        <h2
          className="mt-5 text-3xl font-semibold text-foreground"
          id="payment-result-heading"
        >
          {error ? "Unable to confirm payment" : (copy?.title ?? "Checking payment")}
        </h2>
        <p className="mx-auto mt-3 max-w-lg text-sm leading-6 text-muted-foreground">
          {error ?? copy?.detail}
        </p>
        {payment ? (
          <p className="mt-5 text-sm font-semibold text-foreground">
            {payment.plan_code ?? "Plan"} ·{" "}
            {formatMoney(payment.amount_minor, payment.currency)}
          </p>
        ) : null}
        <div className="mt-7 flex flex-wrap justify-center gap-3">
          {error || (payment && processingStatuses.has(payment.status)) ? (
            <button
              className={secondaryButtonClassName}
              onClick={refresh}
              type="button"
            >
              Check again
            </button>
          ) : null}
          {payment && processingStatuses.has(payment.status) ? (
            <button
              className={secondaryButtonClassName}
              disabled={busy}
              onClick={() => {
                setBusy(true);
                void cancelHostedCheckout(payment.payment_id)
                  .then(setPayment)
                  .catch((caught: unknown) =>
                    setError(
                      caught instanceof Error
                        ? caught.message
                        : "Checkout could not be cancelled.",
                    ),
                  )
                  .finally(() => setBusy(false));
              }}
              type="button"
            >
              I left checkout
            </button>
          ) : null}
          {payment &&
          ["failed", "provider_error", "cancelled"].includes(payment.status) &&
          payment.plan_code ? (
            <Link
              className={primaryButtonClassName}
              to={`/settings/billing/checkout/${payment.plan_code}`}
            >
              Retry checkout
            </Link>
          ) : null}
          <Link
            className={
              payment?.status === "succeeded"
                ? primaryButtonClassName
                : secondaryButtonClassName
            }
            to="/settings/billing"
          >
            View billing
          </Link>
        </div>
        <p className="mt-7 border-t border-border pt-5 text-xs text-muted-foreground">
          Status shown from the authenticated billing API for payment{" "}
          {paymentId ?? "unknown"}. Query-string success flags are ignored.
        </p>
      </div>
    </section>
  );
}
