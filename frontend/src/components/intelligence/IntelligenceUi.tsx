import type { ReactElement, ReactNode } from "react";

import { StatusBadge, type StatusBadgeStatus } from "../StatusBadge";

export const panelClassName =
  "rounded-lg border border-border bg-card p-5 shadow-panel";
export const inputClassName =
  "mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2 text-sm text-foreground";

// eslint-disable-next-line react-refresh/only-export-components
export function statusTone(status: string): StatusBadgeStatus {
  if (
    [
      "healthy",
      "stable",
      "succeeded",
      "completed",
      "eligible",
      "resolved",
      "better",
    ].includes(status)
  )
    return "healthy";
  if (["critical", "failed", "worse"].includes(status)) return "critical";
  if (
    [
      "warning",
      "mixed",
      "blocked_cooldown",
      "blocked_duplicate",
      "blocked_quota",
    ].includes(status)
  )
    return "warning";
  if (
    ["pending", "submitted", "training", "candidate_created", "open"].includes(status)
  )
    return "running";
  return "inactive";
}

export function IntelligenceStatus({
  value,
}: {
  readonly value: string;
}): ReactElement {
  return <StatusBadge label={value.replaceAll("_", " ")} status={statusTone(value)} />;
}

export function MetricGrid({
  items,
}: {
  readonly items: readonly { label: string; value: ReactNode }[];
}): ReactElement {
  return (
    <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <div className={panelClassName} key={item.label}>
          <dt className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {item.label}
          </dt>
          <dd className="mt-2 break-words text-xl font-semibold text-foreground">
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function KeyValues({
  items,
}: {
  readonly items: readonly { label: string; value: ReactNode }[];
}): ReactElement {
  return (
    <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((item) => (
        <div className="rounded-md bg-elevated p-4" key={item.label}>
          <dt className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {item.label}
          </dt>
          <dd className="mt-1 break-words text-sm font-medium text-foreground">
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export const formatDate = (value: string | null): string =>
  value ? new Date(value).toLocaleString() : "Not available";
