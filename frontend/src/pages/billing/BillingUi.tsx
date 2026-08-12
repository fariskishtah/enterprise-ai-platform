import type { ReactElement } from "react";

import { StatusBadge, type StatusBadgeStatus } from "../../components/StatusBadge";

export const billingPanelClassName =
  "rounded-xl border border-border bg-card p-5 shadow-panel sm:p-6";

// eslint-disable-next-line react-refresh/only-export-components
export const entitlementLabels: Readonly<Record<string, string>> = {
  advanced_reports: "Advanced reports",
  audit_log: "Audit log",
  document_storage_gb: "Document storage",
  document_storage_bytes: "Document storage",
  documents: "Documents",
  factories: "Factories",
  machines: "Machines",
  model_training: "Model training",
  monthly_rag_queries: "Monthly AI assistant queries",
  scheduled_reports: "Scheduled reports",
  team_members: "Team members",
  training_concurrency: "Concurrent training jobs",
};

// eslint-disable-next-line react-refresh/only-export-components
export function formatMoney(amountMinor: number, currency = "EGP"): string {
  return new Intl.NumberFormat("en-EG", {
    currency,
    style: "currency",
  }).format(amountMinor / 100);
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatBillingDate(value: string | null): string {
  return value === null
    ? "Not available"
    : new Intl.DateTimeFormat("en-EG", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value));
}

function billingStatusTone(status: string): StatusBadgeStatus {
  if (["active", "trialing", "succeeded", "paid"].includes(status)) {
    return "healthy";
  }
  if (["pending", "creating", "incomplete", "open"].includes(status)) return "running";
  if (
    ["past_due", "refunded", "reversed", "under_review", "superseded"].includes(status)
  )
    return "warning";
  if (["failed", "provider_error", "suspended", "quarantined"].includes(status)) {
    return "critical";
  }
  return "inactive";
}

export function BillingStatus({ status }: { readonly status: string }): ReactElement {
  return (
    <StatusBadge
      label={status.replaceAll("_", " ")}
      status={billingStatusTone(status)}
    />
  );
}
