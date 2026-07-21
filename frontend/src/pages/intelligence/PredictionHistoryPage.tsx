import { useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";
import {
  listPredictionEvents,
  type PredictionEventPage,
  type PredictionEventStatus,
} from "../../api/predictions";
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
export function PredictionHistoryPage(): ReactElement {
  const { role } = useAuth();
  const [page, setPage] = useState<PredictionEventPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [model, setModel] = useState("");
  const [version, setVersion] = useState("");
  const [status, setStatus] = useState<PredictionEventStatus | "">("");
  const [applied, setApplied] = useState({
    model: "",
    version: "",
    status: "" as PredictionEventStatus | "",
  });
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (role === "operator") return;
    const c = new AbortController();
    let active = true;
    listPredictionEvents({
      limit: LIMIT,
      offset,
      modelName: applied.model || undefined,
      version: applied.version || undefined,
      status: applied.status || undefined,
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
          setError(e instanceof Error ? e.message : "Prediction history unavailable.");
      });
    return () => {
      active = false;
      c.abort();
    };
  }, [applied, offset, role]);
  if (role === "operator")
    return (
      <section>
        <PageHeader
          eyebrow="Predictions"
          headingId="history-heading"
          title="Prediction history"
          description="Prediction-event history is restricted to administrators and engineers."
        />
        <div className="mt-6">
          <EmptyState
            title="Restricted history"
            description="Operators can execute predictions but cannot access privacy-preserving event history."
          />
        </div>
      </section>
    );
  return (
    <section>
      <PageHeader
        eyebrow="Predictions"
        headingId="history-heading"
        title="Prediction history"
        description="Privacy-preserving event summaries. Raw feature matrices and raw prediction outputs are never exposed here."
      />
      <form
        className="mt-6 grid gap-3 rounded-lg border border-border bg-card p-4 md:grid-cols-4"
        onSubmit={(e) => {
          e.preventDefault();
          setOffset(0);
          setApplied({ model, version, status });
        }}
      >
        <label className="text-sm">
          Model
          <input
            className={inputClassName}
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
        </label>
        <label className="text-sm">
          Version
          <input
            className={inputClassName}
            value={version}
            onChange={(e) => setVersion(e.target.value)}
          />
        </label>
        <label className="text-sm">
          Status
          <select
            className={inputClassName}
            value={status}
            onChange={(e) => setStatus(e.target.value as PredictionEventStatus | "")}
          >
            <option value="">All</option>
            <option value="succeeded">Succeeded</option>
            <option value="failed">Failed</option>
          </select>
        </label>
        <button
          className="self-end rounded-md bg-purple-700 px-4 py-2 text-sm font-semibold text-white"
          type="submit"
        >
          Apply filters
        </button>
      </form>
      {error ? (
        <div className="mt-5">
          <InlineError message={error} onRetry={() => setApplied({ ...applied })} />
        </div>
      ) : page === null ? (
        <div className="mt-5">
          <LoadingSkeleton />
        </div>
      ) : page.total === 0 ? (
        <div className="mt-5">
          <EmptyState
            title="No prediction events"
            description="No authorized events match these filters."
          />
        </div>
      ) : (
        <div className="mt-5">
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <table className="min-w-full text-left text-sm">
              <thead>
                <tr>
                  <th className="px-4 py-3">Model/version</th>
                  <th className="px-4 py-3">Task</th>
                  <th className="px-4 py-3">Rows</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Completed</th>
                  <th className="px-4 py-3">Action</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((item) => (
                  <tr className="border-t border-border" key={item.event_id}>
                    <td className="px-4 py-3">
                      {item.registered_model_name} /{" "}
                      {item.resolved_model_version ?? "unresolved"}
                    </td>
                    <td className="px-4 py-3">{item.trainer_key.task_type}</td>
                    <td className="px-4 py-3">{item.row_count}</td>
                    <td className="px-4 py-3">
                      <IntelligenceStatus value={item.status} />
                    </td>
                    <td className="px-4 py-3">{formatDate(item.completed_at)}</td>
                    <td className="px-4 py-3">
                      <Link
                        className="font-semibold text-link"
                        to={`/predictions/history/${item.event_id}`}
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
