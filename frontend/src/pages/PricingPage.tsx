import { useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { listBillingPlans, type BillingPlan } from "../api/billing";
import { isRequestCancelled } from "../api/client";
import { hasLegacyRoleAccess } from "../auth/permissions";
import { useAuth } from "../auth/useAuth";
import { LegalFooter } from "../components/LegalFooter";

const entitlementLabels: Readonly<Record<string, string>> = {
  advanced_reports: "Advanced reports",
  audit_log: "Audit log",
  document_storage_gb: "GB document storage",
  documents: "Documents",
  factories: "Factories",
  machines: "Machines",
  model_training: "Model training",
  monthly_rag_queries: "Monthly AI assistant queries",
  scheduled_reports: "Scheduled reports",
  team_members: "Team members",
  training_concurrency: "Concurrent training jobs",
};

function Price({ plan }: { readonly plan: BillingPlan }): ReactElement {
  return (
    <p className="mt-6 flex items-end gap-2 text-foreground">
      <span className="text-4xl font-semibold tracking-tight">
        {(plan.monthly_price_minor / 100).toLocaleString("en-EG")}
      </span>
      <span className="pb-1 text-sm font-medium text-secondary-foreground">
        EGP / access period
      </span>
    </p>
  );
}

export function PricingPage(): ReactElement {
  const { isAuthenticated, role } = useAuth();
  const [plans, setPlans] = useState<readonly BillingPlan[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listBillingPlans(controller.signal)
      .then((response) => {
        setPlans(response.items);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal)) {
          setError(
            caught instanceof Error
              ? caught.message
              : "Plans are temporarily unavailable.",
          );
        }
      });
    return () => controller.abort();
  }, [revision]);

  const canManageBilling = role !== null && hasLegacyRoleAccess(role, ["admin"]);

  return (
    <div className="min-h-screen bg-canvas text-foreground">
      <main className="px-5 py-10 sm:px-8 lg:px-12">
        <header className="mx-auto flex max-w-7xl items-center justify-between gap-4">
          <Link
            className="text-sm font-bold uppercase tracking-[0.18em] text-purple-800"
            to="/"
          >
            FK SOLUTIONS
          </Link>
          <Link
            className="rounded-md border border-border bg-card px-4 py-2 text-sm font-semibold hover:border-purple-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-700"
            to={isAuthenticated ? "/" : "/login"}
          >
            {isAuthenticated ? "Open workspace" : "Sign in"}
          </Link>
        </header>
        <section
          className="mx-auto mt-16 max-w-3xl text-center"
          aria-labelledby="pricing-heading"
        >
          <p className="text-sm font-semibold uppercase tracking-wider text-eyebrow">
            Straightforward pricing
          </p>
          <h1
            className="mt-3 text-4xl font-semibold tracking-tight sm:text-5xl"
            id="pricing-heading"
          >
            Choose the operating scale your team needs
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-base leading-7 text-secondary-foreground">
            Prices are backend-authoritative and shown in Egyptian pounds before
            applicable taxes. Each payment buys one fixed access period; renewal
            requires a new checkout and is never charged automatically.
          </p>
        </section>
        {error ? (
          <div
            className="mx-auto mt-10 max-w-2xl rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800"
            role="alert"
          >
            <p>{error}</p>
            <button
              className="mt-3 font-semibold underline"
              onClick={() => {
                setError(null);
                setPlans([]);
                setRevision((value) => value + 1);
              }}
              type="button"
            >
              Try again
            </button>
          </div>
        ) : null}
        {!error && plans.length === 0 ? (
          <div
            className="mx-auto mt-12 h-96 max-w-7xl animate-pulse rounded-xl bg-muted"
            aria-label="Loading plans"
            role="status"
          />
        ) : null}
        <div className="mx-auto mt-12 grid max-w-7xl gap-6 lg:grid-cols-3">
          {plans.map((plan) => (
            <article
              className={`rounded-xl border bg-card p-7 shadow-sm ${plan.code === "professional" ? "border-purple-500 ring-2 ring-purple-100" : "border-border"}`}
              key={plan.code}
            >
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-xl font-semibold">{plan.name}</h2>
                {plan.code === "professional" ? (
                  <span className="rounded-full bg-purple-100 px-3 py-1 text-xs font-semibold text-purple-900">
                    Most popular
                  </span>
                ) : null}
              </div>
              <p className="mt-3 min-h-12 text-sm leading-6 text-secondary-foreground">
                {plan.description}
              </p>
              <Price plan={plan} />
              <ul className="mt-7 space-y-3 border-t border-border pt-6">
                {Object.entries(plan.entitlements).map(([key, value]) => (
                  <li
                    className="flex gap-3 text-sm text-secondary-foreground"
                    key={key}
                  >
                    <span
                      aria-hidden="true"
                      className={`font-bold ${value === false ? "text-neutral-400" : "text-emerald-700"}`}
                    >
                      {value === false ? "—" : "✓"}
                    </span>
                    {typeof value === "boolean"
                      ? `${value ? "Includes" : "Excludes"} ${entitlementLabels[key] ?? key}`
                      : `${value.toLocaleString()} ${entitlementLabels[key] ?? key}`}
                  </li>
                ))}
              </ul>
              <Link
                className="mt-8 flex w-full justify-center rounded-md bg-purple-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-purple-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-700"
                to={
                  canManageBilling
                    ? `/settings/billing/checkout/${plan.code}`
                    : isAuthenticated
                      ? "/settings"
                      : "/register"
                }
              >
                {canManageBilling
                  ? `Choose ${plan.name}`
                  : isAuthenticated
                    ? "Contact your administrator"
                    : "Create workspace"}
              </Link>
            </article>
          ))}
        </div>
      </main>
      <LegalFooter />
    </div>
  );
}
