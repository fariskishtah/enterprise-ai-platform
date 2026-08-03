import { useCallback, useEffect, useState, type ReactElement } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  cancelHostedCheckout,
  getPaymentStatus,
  resolveBillingReturn,
  type PaymentStatus,
} from "../../api/billing";
import { isRequestCancelled } from "../../api/client";
import {
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { BillingStatus, billingPanelClassName, formatMoney } from "./BillingUi";

const MAXIMUM_POLL_ATTEMPTS = 7;

function isProcessing(payment: PaymentStatus): boolean {
  return (
    payment.checkout_intent_status === "open" &&
    ["pending", "authorized_not_captured"].includes(payment.provider_decision)
  );
}

function resultCopy(payment: PaymentStatus): {
  readonly detail: string;
  readonly title: string;
} {
  if (
    payment.provider_decision === "under_review" ||
    payment.provider_decision === "quarantined" ||
    (payment.provider_decision === "succeeded_eligible" &&
      payment.checkout_intent_status === "superseded")
  )
    return {
      title: "Payment under review",
      detail:
        "We received payment information that needs a finance review. Paid access has not been changed automatically.",
    };
  if (
    payment.status === "succeeded" &&
    payment.provider_decision === "succeeded_eligible"
  )
    return {
      title: "Payment verified",
      detail:
        "A verified, eligible provider event was applied. Your prepaid access period is now available in billing.",
    };
  if (payment.checkout_intent_status === "expired")
    return {
      title: "Checkout expired",
      detail:
        "This hosted checkout is no longer active. Start a new checkout to continue.",
    };
  if (payment.status === "failed" || payment.status === "provider_error")
    return {
      title: "Payment was declined",
      detail: "No paid access was granted. You can safely start a new checkout.",
    };
  if (payment.checkout_intent_status === "cancelled")
    return {
      title: "Checkout cancelled",
      detail:
        "No paid access was granted by this browser action. A later verified provider event remains authoritative.",
    };
  if (payment.provider_decision === "refunded")
    return {
      title: "Payment refunded",
      detail:
        "The provider reported a refund. Review the resulting access state in billing.",
    };
  if (payment.provider_decision === "reversed")
    return {
      title: "Payment reversed",
      detail:
        "The provider reversed this payment. Review the resulting access state in billing.",
    };
  return {
    title: "Confirming payment",
    detail:
      "We are waiting for an eligible provider event. Redirect values are not accepted as proof of payment.",
  };
}

export function BillingReturnPage(): ReactElement {
  const [parameters] = useSearchParams();
  const returnState = parameters.get("state");
  const [payment, setPayment] = useState<PaymentStatus | null>(null);
  const [error, setError] = useState<string | null>(
    returnState === null
      ? "This payment return link is missing its secure state."
      : null,
  );
  const [resolveRevision, setResolveRevision] = useState(0);
  const [pollAttempt, setPollAttempt] = useState(0);
  const [pollRevision, setPollRevision] = useState(0);
  const [timedOut, setTimedOut] = useState(false);
  const [busy, setBusy] = useState(false);
  const paymentId = payment?.payment_id;
  const shouldPoll = payment !== null && isProcessing(payment);

  useEffect(() => {
    if (returnState === null || payment !== null) return;
    const controller = new AbortController();
    resolveBillingReturn(returnState, controller.signal)
      .then((value) => {
        setPayment(value);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal))
          setError(
            caught instanceof Error
              ? caught.message
              : "This payment return link is unavailable.",
          );
      });
    return () => controller.abort();
  }, [payment, resolveRevision, returnState]);

  useEffect(() => {
    if (paymentId === undefined || !shouldPoll) return;
    const controller = new AbortController();
    let nextPoll: number | null = null;
    getPaymentStatus(paymentId, controller.signal)
      .then((value) => {
        setPayment(value);
        setError(null);
        if (isProcessing(value)) {
          if (pollAttempt >= MAXIMUM_POLL_ATTEMPTS) {
            setTimedOut(true);
          } else {
            const delay = Math.min(1000 * 2 ** pollAttempt, 8000);
            nextPoll = window.setTimeout(
              () => setPollAttempt((attempt) => attempt + 1),
              delay,
            );
          }
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
  }, [paymentId, pollAttempt, pollRevision, shouldPoll]);

  const refresh = useCallback(() => {
    setError(null);
    setTimedOut(false);
    if (payment === null) {
      setResolveRevision((value) => value + 1);
    } else {
      setPollAttempt(0);
      setPollRevision((value) => value + 1);
    }
  }, [payment]);

  const copy = payment ? resultCopy(payment) : null;
  const needsReview =
    payment?.provider_decision === "under_review" ||
    payment?.provider_decision === "quarantined" ||
    (payment?.provider_decision === "succeeded_eligible" &&
      payment.checkout_intent_status === "superseded");
  const canRetryCheckout =
    payment?.plan_code !== null &&
    payment !== null &&
    ["failed", "expired", "cancelled"].includes(payment.checkout_intent_status);

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
            <BillingStatus
              status={needsReview ? "under_review" : payment.checkout_intent_status}
            />
          </div>
        ) : null}
        <h2
          className="mt-5 text-3xl font-semibold text-foreground"
          id="payment-result-heading"
        >
          {error ? "Unable to confirm payment" : (copy?.title ?? "Checking payment")}
        </h2>
        <p className="mx-auto mt-3 max-w-lg text-sm leading-6 text-muted-foreground">
          {error ??
            (timedOut
              ? "Confirmation is taking longer than expected. You can check again without creating another payment."
              : copy?.detail)}
        </p>
        {payment ? (
          <p className="mt-5 text-sm font-semibold text-foreground">
            {payment.plan_code ?? "Plan"} ·{" "}
            {formatMoney(payment.amount_minor, payment.currency)}
          </p>
        ) : null}
        <div className="mt-7 flex flex-wrap justify-center gap-3">
          {error || timedOut || (payment !== null && isProcessing(payment)) ? (
            <button
              className={secondaryButtonClassName}
              onClick={refresh}
              type="button"
            >
              Check again
            </button>
          ) : null}
          {payment && isProcessing(payment) ? (
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
              {busy ? "Saving…" : "I left checkout"}
            </button>
          ) : null}
          {canRetryCheckout && payment?.plan_code ? (
            <Link
              className={primaryButtonClassName}
              to={`/settings/billing/checkout/${payment.plan_code}`}
            >
              Start new checkout
            </Link>
          ) : null}
          {needsReview ? (
            <Link className={primaryButtonClassName} to="/support">
              Contact support
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
          Status is loaded from the authenticated billing API. Browser success, amount,
          status, plan, and tenant query values are ignored.
        </p>
      </div>
    </section>
  );
}
