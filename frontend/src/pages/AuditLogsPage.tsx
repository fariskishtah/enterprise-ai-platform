import { useEffect, useState, type ReactElement } from "react";

import { downloadAuditEvents, listAuditEvents, type AuditPage } from "../api/audit";
import { isRequestCancelled } from "../api/client";
import { useAuth } from "../auth/useAuth";
import {
  EmptyState,
  InlineError,
  LoadingSkeleton,
  PaginationControls,
  secondaryButtonClassName,
} from "../components/hierarchy/ResourceStates";
import {
  IntelligenceStatus,
  formatDate,
  inputClassName,
  panelClassName,
} from "../components/intelligence/IntelligenceUi";
import { PageHeader } from "../components/ui/PageHeader";

const LIMIT = 50;

export function AuditLogsPage(): ReactElement {
  const { role } = useAuth();
  const [page, setPage] = useState<AuditPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [result, setResult] = useState<"" | "failure" | "success">("");
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [exporting, setExporting] = useState<"csv" | "json" | null>(null);

  useEffect(() => {
    if (role !== "admin") return;
    const controller = new AbortController();
    listAuditEvents({
      action: action || undefined,
      offset,
      resourceType: resourceType || undefined,
      result: result || undefined,
      signal: controller.signal,
    })
      .then((value) => {
        setPage(value);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal))
          setError(
            caught instanceof Error ? caught.message : "Audit events unavailable.",
          );
      });
    return () => controller.abort();
  }, [action, offset, resourceType, result, revision, role]);

  if (role !== "admin")
    return (
      <section>
        <PageHeader
          eyebrow="Governance"
          headingId="audit-logs-heading"
          title="Audit Logs"
          description="The unified company audit trail is restricted to administrators."
        />
        <div className="mt-6">
          <EmptyState
            title="Administrator access required"
            description="Operational pages continue to show the activity appropriate for your role."
          />
        </div>
      </section>
    );

  return (
    <section>
      <PageHeader
        eyebrow="Governance"
        headingId="audit-logs-heading"
        title="Audit Logs"
        description="Append-only company security and operational events with bounded, redacted metadata."
        actions={
          <>
            <button
              className={secondaryButtonClassName}
              disabled={exporting !== null}
              onClick={() => {
                setExporting("csv");
                void downloadAuditEvents("csv")
                  .catch((caught: unknown) =>
                    setError(
                      caught instanceof Error ? caught.message : "Export unavailable.",
                    ),
                  )
                  .finally(() => setExporting(null));
              }}
              type="button"
            >
              Export CSV
            </button>
            <button
              className={secondaryButtonClassName}
              disabled={exporting !== null}
              onClick={() => {
                setExporting("json");
                void downloadAuditEvents("json")
                  .catch((caught: unknown) =>
                    setError(
                      caught instanceof Error ? caught.message : "Export unavailable.",
                    ),
                  )
                  .finally(() => setExporting(null));
              }}
              type="button"
            >
              Export JSON
            </button>
          </>
        }
      />
      <div className={`${panelClassName} mt-6 grid gap-4 md:grid-cols-3`}>
        <label className="text-sm font-medium">
          Exact action
          <input
            className={inputClassName}
            onChange={(event) => {
              setOffset(0);
              setAction(event.target.value);
            }}
            placeholder="user.created"
            value={action}
          />
        </label>
        <label className="text-sm font-medium">
          Resource type
          <input
            className={inputClassName}
            onChange={(event) => {
              setOffset(0);
              setResourceType(event.target.value);
            }}
            placeholder="user"
            value={resourceType}
          />
        </label>
        <label className="text-sm font-medium">
          Result
          <select
            className={inputClassName}
            onChange={(event) => {
              setOffset(0);
              setResult(event.target.value as "" | "failure" | "success");
            }}
            value={result}
          >
            <option value="">All results</option>
            <option value="success">Success</option>
            <option value="failure">Failure</option>
          </select>
        </label>
      </div>
      {error ? (
        <div className="mt-5">
          <InlineError
            message={error}
            onRetry={() => {
              setError(null);
              setRevision((value) => value + 1);
            }}
          />
        </div>
      ) : !page ? (
        <div className="mt-5">
          <LoadingSkeleton label="Loading audit events" />
        </div>
      ) : page.items.length === 0 ? (
        <div className="mt-5">
          <EmptyState
            title="No audit events"
            description="No company events match the selected filters."
          />
        </div>
      ) : (
        <div className="mt-5 overflow-x-auto rounded-lg border border-border bg-card">
          <table className="min-w-[1000px] w-full text-left text-sm">
            <thead className="bg-muted text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Action</th>
                <th className="px-4 py-3">Actor</th>
                <th className="px-4 py-3">Resource</th>
                <th className="px-4 py-3">Result</th>
                <th className="px-4 py-3">Detail</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((event) => (
                <tr className="border-t border-border align-top" key={event.id}>
                  <td className="px-4 py-3">{formatDate(event.occurred_at)}</td>
                  <td className="px-4 py-3 font-semibold text-foreground">
                    {event.action}
                  </td>
                  <td className="px-4 py-3">
                    {event.actor_role ?? "System"}
                    <div className="font-mono text-xs text-muted-foreground">
                      {event.actor_user_id ?? "Not available"}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    {event.resource_type}
                    <div className="font-mono text-xs text-muted-foreground">
                      {event.resource_id ?? "Not available"}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <IntelligenceStatus
                      value={event.result === "success" ? "healthy" : "failed"}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <details>
                      <summary className="cursor-pointer font-semibold text-link">
                        Safe metadata
                      </summary>
                      <pre className="mt-2 max-w-md whitespace-pre-wrap text-xs text-secondary-foreground">
                        {JSON.stringify(event.safe_metadata, null, 2)}
                      </pre>
                      <p className="mt-2 text-xs text-muted-foreground">
                        Request: {event.request_id ?? "Unavailable"} · Correlation:{" "}
                        {event.correlation_id ?? "Unavailable"}
                      </p>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-4 pb-4">
            <PaginationControls
              limit={LIMIT}
              offset={offset}
              onPageChange={setOffset}
              total={page.total}
            />
          </div>
        </div>
      )}
    </section>
  );
}
