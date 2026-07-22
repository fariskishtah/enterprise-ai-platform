import type { ReactElement, ReactNode } from "react";

import type { AutoMLStudyStatus, AutoMLTrialStatus } from "../../api/automl";
import { StatusBadge, type StatusBadgeStatus } from "../StatusBadge";

// eslint-disable-next-line react-refresh/only-export-components
export const terminalStudyStatuses: ReadonlySet<AutoMLStudyStatus> = new Set([
  "cancelled",
  "failed",
  "succeeded",
]);

export function AutoMLStatusBadge({
  status,
}: {
  readonly status: AutoMLStudyStatus | AutoMLTrialStatus;
}): ReactElement {
  const tones: Record<AutoMLTrialStatus, StatusBadgeStatus> = {
    cancelled: "inactive",
    failed: "critical",
    pruned: "inactive",
    queued: "warning",
    running: "running",
    succeeded: "healthy",
  };
  return (
    <StatusBadge
      label={status[0].toUpperCase() + status.slice(1)}
      status={tones[status]}
    />
  );
}

export function AutoMLCard({
  children,
}: {
  readonly children: ReactNode;
}): ReactElement {
  return (
    <section className="rounded-lg border border-border bg-card p-5 shadow-panel">
      {children}
    </section>
  );
}

export function KeyValues({
  values,
}: {
  readonly values: readonly { readonly label: string; readonly value: ReactNode }[];
}): ReactElement {
  return (
    <dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {values.map(({ label, value }) => (
        <div className="min-w-0" key={label}>
          <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {label}
          </dt>
          <dd className="mt-1 break-words text-sm font-semibold text-foreground">
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatMetric(value: number | null): string {
  return value === null
    ? "Not available"
    : value.toLocaleString(undefined, { maximumFractionDigits: 8 });
}

// eslint-disable-next-line react-refresh/only-export-components
export function compactParameters(value: Readonly<Record<string, unknown>>): string {
  const entries = Object.entries(value);
  if (entries.length === 0) return "Default parameters";
  return entries
    .slice(0, 3)
    .map(([key, item]) => `${key}=${String(item)}`)
    .join(", ");
}
