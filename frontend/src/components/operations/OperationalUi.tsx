/* eslint-disable react-refresh/only-export-components */
import type { ReactElement, ReactNode } from "react";

import type {
  ActionPriority,
  ActionStatus,
  OperationalAction,
} from "../../api/operations";
import { presentOperationalError } from "../../product/operationalLanguage";

export const operationalPanelClassName =
  "rounded-lg border border-border bg-card p-5 shadow-panel";
export const operationalInputClassName =
  "mt-1.5 min-h-10 w-full rounded-md border border-border-strong bg-input px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function formatOperationalDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Not recorded";
}

export function ActionPriorityBadge({
  priority,
}: {
  readonly priority: ActionPriority;
}): ReactElement {
  const classes: Record<ActionPriority, string> = {
    critical: "border-red-300 bg-red-50 text-red-800",
    high: "border-orange-300 bg-orange-50 text-orange-900",
    low: "border-border bg-muted text-secondary-foreground",
    medium: "border-amber-300 bg-amber-50 text-amber-900",
  };
  return (
    <span
      className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold capitalize ${classes[priority]}`}
    >
      {priority}
    </span>
  );
}

export function ActionStatusBadge({
  status,
}: {
  readonly status: ActionStatus | string;
}): ReactElement {
  const semantic =
    status === "completed" || status === "resolved"
      ? "border-green-300 bg-green-50 text-green-800"
      : status === "cancelled"
        ? "border-border bg-muted text-secondary-foreground"
        : status === "blocked" || status === "escalated"
          ? "border-red-300 bg-red-50 text-red-800"
          : "border-purple-300 bg-purple-50 text-purple-900";
  return (
    <span
      className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold capitalize ${semantic}`}
    >
      {status.replaceAll("_", " ")}
    </span>
  );
}

export function OperationalError({
  error,
  onRetry,
}: {
  readonly error: unknown;
  readonly onRetry?: () => void;
}): ReactElement {
  const presentation = presentOperationalError(error);
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-5" role="alert">
      <h3 className="font-semibold text-red-950">{presentation.title}</h3>
      <p className="mt-1 text-sm text-red-900">{presentation.message}</p>
      <p className="mt-2 text-sm font-medium text-red-950">
        Next: {presentation.nextStep}
      </p>
      {onRetry ? (
        <button
          className="mt-4 rounded-md border border-red-300 bg-white px-3 py-2 text-sm font-semibold text-red-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700"
          onClick={onRetry}
          type="button"
        >
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function ActionSummaryCard({
  action,
  footer,
}: {
  readonly action: OperationalAction;
  readonly footer?: ReactNode;
}): ReactElement {
  return (
    <article className={`${operationalPanelClassName} border-l-4 border-l-purple-600`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-foreground">{action.title}</h3>
          <p className="mt-1 text-sm text-secondary-foreground">{action.reason}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ActionPriorityBadge priority={action.priority} />
          <ActionStatusBadge status={action.status} />
        </div>
      </div>
      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs font-semibold uppercase text-muted-foreground">Due</dt>
          <dd className="text-foreground">{formatOperationalDate(action.due_at)}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-muted-foreground">
            Assignee
          </dt>
          <dd className="text-foreground">
            {action.assigned_user_id ? "Assigned" : "Unassigned"}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-muted-foreground">
            Updated
          </dt>
          <dd className="text-foreground">
            {formatOperationalDate(action.updated_at)}
          </dd>
        </div>
      </dl>
      {footer ? <div className="mt-4 border-t border-border pt-4">{footer}</div> : null}
    </article>
  );
}
