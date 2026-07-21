import { useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";
import {
  listAlerts,
  type AlertPage,
  type AlertSeverity,
  type AlertStatus,
} from "../../api/alerts";
import {
  EmptyState,
  InlineError,
  LoadingSkeleton,
  PaginationControls,
} from "../../components/hierarchy/ResourceStates";
import {
  IntelligenceStatus,
  formatDate,
  inputClassName,
} from "../../components/intelligence/IntelligenceUi";
import { PageHeader } from "../../components/ui/PageHeader";
import { useAuth } from "../../auth/useAuth";
import { isRequestCancelled } from "../../api/client";
const LIMIT = 20;
export function AlertsPage(): ReactElement {
  const { role } = useAuth();
  const [page, setPage] = useState<AlertPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState<AlertStatus | "">("");
  const [severity, setSeverity] = useState<AlertSeverity | "">("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (role === "operator") return;
    const c = new AbortController();
    let active = true;
    listAlerts({
      limit: LIMIT,
      offset,
      status: status || undefined,
      severity: severity || undefined,
      signal: c.signal,
    })
      .then((value) => {
        if (active) {
          setPage(value);
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (active && !isRequestCancelled(e, c.signal))
          setError(e instanceof Error ? e.message : "Alerts unavailable.");
      });
    return () => {
      active = false;
      c.abort();
    };
  }, [offset, role, severity, status]);
  if (role === "operator")
    return (
      <section>
        <PageHeader
          eyebrow="Monitoring"
          headingId="alerts-heading"
          title="Alerts"
          description="Alert access is restricted to administrators and engineers."
        />
        <div className="mt-6">
          <EmptyState
            title="Restricted alerts"
            description="Operational monitoring remains available without alert-management access."
          />
        </div>
      </section>
    );
  return (
    <section>
      <PageHeader
        eyebrow="Monitoring"
        headingId="alerts-heading"
        title="Alerts"
        description="Deduplicated internal monitoring alerts. Alert creation and external notification settings are not supported."
      />
      <div className="mt-6 flex flex-wrap gap-4">
        <label className="text-sm">
          Status
          <select
            className={inputClassName}
            value={status}
            onChange={(e) => {
              setOffset(0);
              setStatus(e.target.value as AlertStatus | "");
            }}
          >
            <option value="">All</option>
            <option value="open">Open</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
          </select>
        </label>
        <label className="text-sm">
          Severity
          <select
            className={inputClassName}
            value={severity}
            onChange={(e) => {
              setOffset(0);
              setSeverity(e.target.value as AlertSeverity | "");
            }}
          >
            <option value="">All</option>
            <option value="warning">Warning</option>
            <option value="critical">Critical</option>
          </select>
        </label>
      </div>
      {error ? (
        <div className="mt-5">
          <InlineError message={error} onRetry={() => setError(null)} />
        </div>
      ) : !page ? (
        <div className="mt-5">
          <LoadingSkeleton />
        </div>
      ) : !page.total ? (
        <div className="mt-5">
          <EmptyState
            title="No alerts"
            description="No alerts match the current filters."
          />
        </div>
      ) : (
        <div className="mt-5">
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <table className="min-w-full text-left text-sm">
              <thead>
                <tr>
                  <th className="px-4 py-3">Alert</th>
                  <th className="px-4 py-3">Model/version</th>
                  <th className="px-4 py-3">Severity</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Updated</th>
                  <th className="px-4 py-3">Action</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((a) => (
                  <tr className="border-t border-border" key={a.id}>
                    <td className="px-4 py-3">
                      <p className="font-semibold">{a.title}</p>
                      <p className="text-xs text-muted-foreground">
                        {a.occurrence_count} occurrences
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      {a.registered_model_name} / {a.model_version}
                    </td>
                    <td className="px-4 py-3">
                      <IntelligenceStatus value={a.severity} />
                    </td>
                    <td className="px-4 py-3">
                      <IntelligenceStatus value={a.status} />
                    </td>
                    <td className="px-4 py-3">{formatDate(a.updated_at)}</td>
                    <td className="px-4 py-3">
                      <Link
                        className="font-semibold text-link"
                        to={`/monitoring/alerts/${a.id}`}
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
            total={page.total}
            onPageChange={setOffset}
          />
        </div>
      )}
    </section>
  );
}
