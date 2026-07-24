import { useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import { listOperationalAlerts, type OperationalAlertPage } from "../../api/operations";
import {
  EmptyState,
  LoadingSkeleton,
  PaginationControls,
} from "../../components/hierarchy/ResourceStates";
import {
  ActionStatusBadge,
  OperationalError,
  formatOperationalDate,
  operationalInputClassName,
} from "../../components/operations/OperationalUi";
import { PageHeader } from "../../components/ui/PageHeader";

const LIMIT = 20;

export function OperationalAlertsPage(): ReactElement {
  const [page, setPage] = useState<OperationalAlertPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    listOperationalAlerts({
      limit: LIMIT,
      offset,
      severity: severity || undefined,
      signal: controller.signal,
      status: status || undefined,
    })
      .then((value) => {
        if (active) {
          setPage(value);
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
  }, [offset, revision, severity, status]);

  return (
    <section aria-labelledby="alerts-heading">
      <PageHeader
        description="Machine conditions requiring acknowledgement, investigation, or resolution."
        eyebrow="Operations"
        headingId="alerts-heading"
        title="Alerts"
      />
      <div className="mt-6 grid max-w-2xl gap-4 sm:grid-cols-2">
        <label className="text-sm font-semibold text-foreground">
          Status
          <select
            className={operationalInputClassName}
            onChange={(event) => {
              setOffset(0);
              setStatus(event.target.value);
            }}
            value={status}
          >
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="in_progress">In progress</option>
            <option value="escalated">Escalated</option>
            <option value="resolved">Resolved</option>
          </select>
        </label>
        <label className="text-sm font-semibold text-foreground">
          Severity
          <select
            className={operationalInputClassName}
            onChange={(event) => {
              setOffset(0);
              setSeverity(event.target.value);
            }}
            value={severity}
          >
            <option value="">All severities</option>
            <option value="warning">Warning</option>
            <option value="critical">Critical</option>
          </select>
        </label>
      </div>
      <div className="mt-6">
        {error ? (
          <OperationalError
            error={error}
            onRetry={() => {
              setError(null);
              setRevision((value) => value + 1);
            }}
          />
        ) : page === null ? (
          <LoadingSkeleton label="Loading operational alerts" />
        ) : page.items.length === 0 ? (
          <EmptyState
            description="No open alerts require attention for these filters."
            title="No alerts require attention"
          />
        ) : (
          <>
            <div className="overflow-x-auto rounded-lg border border-border bg-card shadow-panel">
              <table className="min-w-full text-left text-sm">
                <thead className="bg-elevated text-foreground">
                  <tr>
                    <th className="px-4 py-3">Alert</th>
                    <th className="px-4 py-3">Severity</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Assigned</th>
                    <th className="px-4 py-3">Updated</th>
                    <th className="px-4 py-3">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((alert) => (
                    <tr
                      className="border-t border-border hover:bg-muted"
                      key={alert.id}
                    >
                      <td className="px-4 py-3">
                        <p className="font-semibold text-foreground">{alert.title}</p>
                        <p className="max-w-md text-xs text-muted-foreground">
                          {alert.safe_summary}
                        </p>
                      </td>
                      <td className="px-4 py-3 capitalize">{alert.severity}</td>
                      <td className="px-4 py-3">
                        <ActionStatusBadge status={alert.status} />
                      </td>
                      <td className="px-4 py-3">
                        {alert.assigned_user_id ? "Assigned" : "Unassigned"}
                      </td>
                      <td className="px-4 py-3">
                        {formatOperationalDate(alert.last_detected_at)}
                      </td>
                      <td className="px-4 py-3">
                        <Link
                          className="font-semibold text-link"
                          to={`/monitoring/alerts/${alert.id}`}
                        >
                          Open
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <PaginationControls
              limit={page.limit}
              offset={page.offset}
              onPageChange={setOffset}
              total={page.total}
            />
          </>
        )}
      </div>
    </section>
  );
}
