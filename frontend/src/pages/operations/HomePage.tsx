import { useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import {
  getOperationalSummary,
  listOperationalActions,
  listOperationalAlerts,
  listShifts,
  listTimeline,
  type OperationalAction,
  type OperationalAlert,
  type OperationalSummary,
  type ShiftHandover,
  type TimelineEvent,
} from "../../api/operations";
import { useAuth } from "../../auth/useAuth";
import { EmptyState, LoadingSkeleton } from "../../components/hierarchy/ResourceStates";
import {
  ActionPriorityBadge,
  ActionStatusBadge,
  OperationalError,
  formatOperationalDate,
  operationalPanelClassName,
} from "../../components/operations/OperationalUi";
import { PageHeader } from "../../components/ui/PageHeader";
import { useProductExperience } from "../../product/productExperience";
import { Dashboard } from "../Dashboard";

interface SimpleHomeData {
  readonly actions: readonly OperationalAction[];
  readonly alerts: readonly OperationalAlert[];
  readonly shifts: readonly ShiftHandover[];
  readonly summary: OperationalSummary;
  readonly timeline: readonly TimelineEvent[];
}

export function HomePage(): ReactElement {
  const { features, mode } = useProductExperience();
  return mode === "simple" && features.operations_workflow_enabled ? (
    <SimpleHome />
  ) : (
    <Dashboard />
  );
}

function SimpleHome(): ReactElement {
  const { role } = useAuth();
  const [data, setData] = useState<SimpleHomeData | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.all([
      getOperationalSummary(controller.signal),
      listOperationalActions({ limit: 6, signal: controller.signal }),
      listOperationalAlerts({ limit: 6, signal: controller.signal }),
      listTimeline({ limit: 6, signal: controller.signal }),
      listShifts({ limit: 3, signal: controller.signal }),
    ])
      .then(([summary, actions, alerts, timeline, shifts]) => {
        if (active) {
          setData({
            actions: actions.items,
            alerts: alerts.items,
            shifts: shifts.items,
            summary,
            timeline: timeline.items,
          });
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (active && !isRequestCancelled(caught, controller.signal)) setError(caught);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [revision]);

  if (error)
    return (
      <OperationalError
        error={error}
        onRetry={() => {
          setError(null);
          setRevision((value) => value + 1);
        }}
      />
    );
  if (!data) return <LoadingSkeleton label="Loading operations home" />;

  const openAlerts = Object.entries(data.summary.alert_counts)
    .filter(([status]) => status !== "resolved")
    .reduce((total, [, count]) => total + count, 0);
  const urgentActions =
    (data.summary.action_counts.open ?? 0) +
    (data.summary.action_counts.assigned ?? 0) +
    (data.summary.action_counts.in_progress ?? 0) +
    (data.summary.action_counts.blocked ?? 0);
  const heading =
    role === "operator" ? "Your operations home" : "Factory operations overview";
  const description =
    role === "operator"
      ? "See the machines, alerts, and assigned work that need your attention now."
      : "Review company-scoped machine risk, unresolved work, alerts, and shift status.";

  return (
    <section aria-labelledby="simple-home-heading">
      <PageHeader
        actions={
          <Link
            className="rounded-md bg-purple-700 px-4 py-2 text-sm font-semibold text-white hover:bg-purple-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            to="/operations/actions"
          >
            View required actions
          </Link>
        }
        description={description}
        eyebrow={role === "operator" ? "What needs attention" : "Simple mode"}
        headingId="simple-home-heading"
        title={heading}
      />
      <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Metric
          label="Actions requiring attention"
          value={urgentActions}
          variant={urgentActions > 0 ? "attention" : "normal"}
        />
        <Metric
          label="Overdue actions"
          value={data.summary.overdue_actions}
          variant={data.summary.overdue_actions > 0 ? "critical" : "normal"}
        />
        <Metric
          label="Unresolved alerts"
          value={openAlerts}
          variant={openAlerts > 0 ? "attention" : "normal"}
        />
        <Metric
          label="Active shifts"
          value={data.summary.active_shift_count}
          variant="normal"
        />
      </div>
      {role !== "operator" ? (
        <section
          aria-labelledby="risk-state-heading"
          className={`${operationalPanelClassName} mt-6`}
        >
          <h2 className="text-lg font-semibold text-foreground" id="risk-state-heading">
            Current machine risk states
          </h2>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {["normal", "observe", "warning", "critical", "insufficient_data"].map(
              (state) => (
                <div className="rounded-md bg-elevated p-4" key={state}>
                  <p className="text-xs font-semibold uppercase text-muted-foreground">
                    {state.replaceAll("_", " ")}
                  </p>
                  <p className="mt-2 text-2xl font-semibold text-foreground">
                    {data.summary.risk_counts[state] ?? 0}
                  </p>
                </div>
              ),
            )}
          </div>
        </section>
      ) : null}
      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <section className={operationalPanelClassName}>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold text-foreground">
              Highest-priority actions
            </h2>
            <Link className="text-sm font-semibold text-link" to="/operations/actions">
              All actions
            </Link>
          </div>
          {data.actions.length === 0 ? (
            <EmptyState
              description="There are no pending operational actions."
              title="Nothing requires action"
            />
          ) : (
            <ol className="mt-4 divide-y divide-border">
              {data.actions.map((action) => (
                <li className="py-3" key={action.id}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <Link
                      className="font-semibold text-link"
                      to={`/operations/actions/${action.id}`}
                    >
                      {action.title}
                    </Link>
                    <div className="flex gap-2">
                      <ActionPriorityBadge priority={action.priority} />
                      <ActionStatusBadge status={action.status} />
                    </div>
                  </div>
                  <p className="mt-1 text-sm text-secondary-foreground">
                    {action.recommended_action}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </section>
        <section className={operationalPanelClassName}>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold text-foreground">Open alerts</h2>
            <Link className="text-sm font-semibold text-link" to="/monitoring/alerts">
              All alerts
            </Link>
          </div>
          {data.alerts.length === 0 ? (
            <EmptyState
              description="No open alerts require attention."
              title="No active alerts"
            />
          ) : (
            <ol className="mt-4 divide-y divide-border">
              {data.alerts.map((alert) => (
                <li className="py-3" key={alert.id}>
                  <div className="flex items-start justify-between gap-2">
                    <Link
                      className="font-semibold text-link"
                      to={`/monitoring/alerts/${alert.id}`}
                    >
                      {alert.title}
                    </Link>
                    <ActionStatusBadge status={alert.status} />
                  </div>
                  <p className="mt-1 text-sm text-secondary-foreground">
                    {alert.safe_summary}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
      <div className="mt-6 grid gap-6 xl:grid-cols-[1.4fr_0.6fr]">
        <section className={operationalPanelClassName}>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold text-foreground">
              Recent operational activity
            </h2>
            <Link className="text-sm font-semibold text-link" to="/activity">
              Full activity
            </Link>
          </div>
          {data.timeline.length === 0 ? (
            <p className="mt-4 text-sm text-secondary-foreground">
              Operational events will appear here as work progresses.
            </p>
          ) : (
            <ol className="mt-4 space-y-3">
              {data.timeline.map((event) => (
                <li className="rounded-md bg-elevated p-3" key={event.id}>
                  <p className="font-semibold text-foreground">{event.title}</p>
                  <p className="mt-1 text-sm text-secondary-foreground">
                    {event.detail}
                  </p>
                  <time className="mt-1 block text-xs text-muted-foreground">
                    {formatOperationalDate(event.occurred_at)}
                  </time>
                </li>
              ))}
            </ol>
          )}
        </section>
        <section className={operationalPanelClassName}>
          <h2 className="text-lg font-semibold text-foreground">Current shift</h2>
          {data.shifts.find((shift) => shift.status === "active") ? (
            <ShiftSummary
              shift={data.shifts.find((shift) => shift.status === "active")!}
            />
          ) : (
            <p className="mt-4 text-sm text-secondary-foreground">
              No active shift is recorded.
            </p>
          )}
          <Link
            className="mt-4 inline-block text-sm font-semibold text-link"
            to="/operations/shifts"
          >
            Open shift handover
          </Link>
          <dl className="mt-5 border-t border-border pt-4">
            <dt className="text-xs font-semibold uppercase text-muted-foreground">
              Data freshness
            </dt>
            <dd className="mt-1 text-sm text-foreground">
              {data.summary.data_freshness_seconds === null
                ? "No sensor data available"
                : `${Math.round(data.summary.data_freshness_seconds / 60)} minutes ago`}
            </dd>
          </dl>
        </section>
      </div>
    </section>
  );
}

function Metric({
  label,
  value,
  variant,
}: {
  readonly label: string;
  readonly value: number;
  readonly variant: "attention" | "critical" | "normal";
}): ReactElement {
  const accent =
    variant === "critical"
      ? "border-l-red-600"
      : variant === "attention"
        ? "border-l-orange-500"
        : "border-l-purple-600";
  return (
    <article
      className={`rounded-lg border border-border border-l-4 bg-card p-5 shadow-panel ${accent}`}
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-3 text-3xl font-semibold text-foreground">{value}</p>
    </article>
  );
}

function ShiftSummary({ shift }: { readonly shift: ShiftHandover }): ReactElement {
  return (
    <div className="mt-4 rounded-md bg-elevated p-4">
      <p className="font-semibold text-foreground">
        {shift.team_label || "Factory shift"}
      </p>
      <p className="mt-1 text-sm text-secondary-foreground">
        Started {formatOperationalDate(shift.started_at)}
      </p>
    </div>
  );
}
