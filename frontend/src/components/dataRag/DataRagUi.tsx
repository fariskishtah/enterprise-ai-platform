import type { ReactElement, ReactNode } from "react";

import { StatusBadge, type StatusBadgeStatus } from "../StatusBadge";

export const lifecycleCardClassName =
  "rounded-lg border border-border bg-card p-5 shadow-panel";
export const lifecycleInputClassName =
  "mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2 text-sm text-foreground";

// eslint-disable-next-line react-refresh/only-export-components
export const terminalDatasetVersionStatuses: ReadonlySet<string> = new Set([
  "archived",
  "failed",
  "ready",
]);
// eslint-disable-next-line react-refresh/only-export-components
export const terminalBuildStatuses: ReadonlySet<string> = new Set([
  "cancelled",
  "failed",
  "succeeded",
]);
// eslint-disable-next-line react-refresh/only-export-components
export const terminalMessageStatuses: ReadonlySet<string> = new Set([
  "cancelled",
  "failed",
  "succeeded",
]);

function tone(status: string): StatusBadgeStatus {
  if (["active", "ready", "succeeded"].includes(status)) return "healthy";
  if (["failed"].includes(status)) return "critical";
  if (["draft", "pending", "queued"].includes(status)) return "warning";
  if (
    [
      "building",
      "chunking",
      "embedding",
      "extracting",
      "generating",
      "indexing",
      "processing",
      "retrieving",
      "running",
    ].includes(status)
  )
    return "running";
  return "inactive";
}

export function LifecycleStatus({ status }: { readonly status: string }): ReactElement {
  return <StatusBadge label={status.replaceAll("_", " ")} status={tone(status)} />;
}

export function LifecycleCard({
  children,
}: {
  readonly children: ReactNode;
}): ReactElement {
  return <section className={lifecycleCardClassName}>{children}</section>;
}

export function KeyValueGrid({
  items,
}: {
  readonly items: readonly { readonly label: string; readonly value: ReactNode }[];
}): ReactElement {
  return (
    <dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <div className="min-w-0" key={item.label}>
          <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {item.label}
          </dt>
          <dd className="mt-1 break-words text-sm font-semibold text-foreground">
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function SafeMetadata({
  emptyLabel = "No metadata is available.",
  value,
}: {
  readonly emptyLabel?: string;
  readonly value: Readonly<Record<string, unknown>>;
}): ReactElement {
  const entries = Object.entries(value).slice(0, 50);
  if (entries.length === 0)
    return <p className="text-sm text-muted-foreground">{emptyLabel}</p>;
  return (
    <dl className="grid gap-3 sm:grid-cols-2">
      {entries.map(([key, item]) => (
        <div className="rounded-md bg-elevated p-3" key={key}>
          <dt className="break-words text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {key.replaceAll("_", " ")}
          </dt>
          <dd className="mt-1 break-words text-sm text-foreground">
            {safeValue(item)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function safeValue(value: unknown): string {
  if (value === null) return "Not available";
  if (typeof value === "string") return value.slice(0, 500);
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value))
    return value
      .slice(0, 20)
      .map((item) => safeValue(item))
      .join(", ");
  if (typeof value === "object")
    return Object.entries(value)
      .slice(0, 20)
      .map(([key, item]) => `${key}: ${safeValue(item)}`)
      .join(" · ");
  return "Not available";
}
