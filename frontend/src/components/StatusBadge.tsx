import type { ReactElement } from "react";

export type StatusBadgeStatus =
  "critical" | "healthy" | "inactive" | "running" | "warning";

interface StatusBadgeProps {
  readonly label?: string;
  readonly status: StatusBadgeStatus;
}

const statusStyles: Record<
  StatusBadgeStatus,
  {
    readonly defaultLabel: string;
    readonly marker: string;
    readonly wrapper: string;
  }
> = {
  critical: {
    defaultLabel: "Critical",
    marker: "bg-red-600",
    wrapper: "border-red-200 bg-red-50 text-red-800",
  },
  healthy: {
    defaultLabel: "Healthy",
    marker: "bg-emerald-600",
    wrapper: "border-emerald-200 bg-emerald-50 text-emerald-800",
  },
  inactive: {
    defaultLabel: "Inactive",
    marker: "bg-neutral-500",
    wrapper: "border-neutral-200 bg-neutral-100 text-neutral-700",
  },
  running: {
    defaultLabel: "Running",
    marker: "bg-blue-600",
    wrapper: "border-blue-200 bg-blue-50 text-blue-800",
  },
  warning: {
    defaultLabel: "Warning",
    marker: "bg-amber-500",
    wrapper: "border-amber-200 bg-amber-50 text-amber-900",
  },
};

export function StatusBadge({ label, status }: StatusBadgeProps): ReactElement {
  const style = statusStyles[status];

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-semibold ${style.wrapper}`}
    >
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${style.marker}`} />
      <span>{label ?? style.defaultLabel}</span>
      <span className="sr-only">status</span>
    </span>
  );
}
