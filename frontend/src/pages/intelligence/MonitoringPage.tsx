import { useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";
import { listAlerts, type MonitoringAlert } from "../../api/alerts";
import { listEvaluations, type MonitoringEvaluation } from "../../api/monitoring";
import { getRetrainingStatus, type RetrainingStatus } from "../../api/retraining";
import { useAuth } from "../../auth/useAuth";
import {
  EmptyState,
  InlineError,
  InlineNotice,
  LoadingSkeleton,
} from "../../components/hierarchy/ResourceStates";
import {
  IntelligenceStatus,
  MetricGrid,
  formatDate,
  inputClassName,
  panelClassName,
} from "../../components/intelligence/IntelligenceUi";
import { PageHeader } from "../../components/ui/PageHeader";
import { isRequestCancelled } from "../../api/client";
export function MonitoringPage(): ReactElement {
  const { role } = useAuth();
  const canAlerts = role === "admin" || role === "engineer";
  const [evaluations, setEvaluations] = useState<
    readonly MonitoringEvaluation[] | null
  >(null);
  const [alerts, setAlerts] = useState<readonly MonitoringAlert[]>([]);
  const [status, setStatus] = useState<RetrainingStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const [version, setVersion] = useState("");
  useEffect(() => {
    const c = new AbortController();
    let active = true;
    Promise.allSettled([
      listEvaluations({ limit: 10, offset: 0, signal: c.signal }),
      getRetrainingStatus(c.signal),
      canAlerts
        ? listAlerts({ limit: 5, offset: 0, status: "open", signal: c.signal })
        : Promise.resolve({ items: [], total: 0, limit: 5, offset: 0 }),
    ]).then(([evaluationsResult, statusResult, alertsResult]) => {
      if (!active) return;
      if (evaluationsResult.status === "fulfilled")
        setEvaluations(evaluationsResult.value.items);
      if (statusResult.status === "fulfilled") setStatus(statusResult.value);
      if (alertsResult.status === "fulfilled") setAlerts(alertsResult.value.items);
      const nextWarnings: string[] = [];
      if (
        alertsResult.status === "rejected" &&
        !isRequestCancelled(alertsResult.reason, c.signal)
      )
        nextWarnings.push(
          alertsResult.reason instanceof Error
            ? `Alerts: ${alertsResult.reason.message}`
            : "Alerts are unavailable.",
        );
      setWarnings(nextWarnings);
      const coreFailure = [evaluationsResult, statusResult].find(
        (result) =>
          result.status === "rejected" && !isRequestCancelled(result.reason, c.signal),
      );
      if (coreFailure?.status === "rejected")
        setError(
          coreFailure.reason instanceof Error
            ? coreFailure.reason.message
            : "Monitoring unavailable.",
        );
      else setError(null);
    });
    return () => {
      active = false;
      c.abort();
    };
  }, [canAlerts]);
  if (error) return <InlineError message={error} onRetry={() => location.reload()} />;
  if (!evaluations || !status) return <LoadingSkeleton />;
  return (
    <section>
      <PageHeader
        eyebrow="Intelligence operations"
        headingId="monitoring-heading"
        title="Monitoring"
        description="Persisted monitoring evaluations and exact-version operational intelligence. Detailed reports always require model/version context."
        actions={
          canAlerts ? (
            <Link className="font-semibold text-link" to="/monitoring/alerts">
              Open alerts
            </Link>
          ) : undefined
        }
      />
      {warnings.length ? (
        <div className="mt-5">
          <InlineNotice>{warnings.join(" ")}</InlineNotice>
        </div>
      ) : null}
      <div className="mt-6">
        <MetricGrid
          items={[
            { label: "Recent evaluations", value: evaluations.length },
            { label: "Active retraining", value: status.active_requests },
            { label: "Completed retraining", value: status.completed_requests },
            { label: "Open alerts", value: canAlerts ? alerts.length : "Restricted" },
          ]}
        />
      </div>
      <form
        className={`${panelClassName} mt-6 grid gap-4 md:grid-cols-[1fr_1fr_auto]`}
        onSubmit={(e) => {
          e.preventDefault();
          location.assign(
            `/monitoring/models/${encodeURIComponent(model)}/versions/${encodeURIComponent(version)}`,
          );
        }}
      >
        <label className="text-sm">
          Registered model
          <input
            required
            className={inputClassName}
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
        </label>
        <label className="text-sm">
          Exact version
          <input
            required
            pattern="[1-9][0-9]*"
            className={inputClassName}
            value={version}
            onChange={(e) => setVersion(e.target.value)}
          />
        </label>
        <button
          className="self-end rounded-md bg-purple-700 px-4 py-2 text-sm font-semibold text-white"
          type="submit"
        >
          Open exact monitoring
        </button>
      </form>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div>
          <h2 className="text-lg font-semibold text-foreground">Recent evaluations</h2>
          {evaluations.length ? (
            <div className="mt-3 space-y-3">
              {evaluations.map((item) => (
                <Link
                  className={`${panelClassName} block`}
                  key={item.id}
                  to={`/monitoring/evaluations/${item.id}`}
                >
                  <div className="flex justify-between gap-3">
                    <div>
                      <p className="font-semibold text-foreground">
                        {item.registered_model_name} · {item.model_version}
                      </p>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {formatDate(item.created_at)} · {item.evaluated_sample_count}{" "}
                        samples
                      </p>
                    </div>
                    <IntelligenceStatus value={item.overall_status} />
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <div className="mt-3">
              <EmptyState
                title="No evaluations"
                description="No persisted monitoring evaluations are available."
              />
            </div>
          )}
        </div>
        {canAlerts ? (
          <div>
            <h2 className="text-lg font-semibold text-foreground">Attention</h2>
            {alerts.length ? (
              <div className="mt-3 space-y-3">
                {alerts.map((item) => (
                  <Link
                    className={`${panelClassName} block`}
                    key={item.id}
                    to={`/monitoring/alerts/${item.id}`}
                  >
                    <div className="flex justify-between gap-3">
                      <div>
                        <p className="font-semibold text-foreground">{item.title}</p>
                        <p className="mt-1 text-sm text-muted-foreground">
                          {item.registered_model_name} · {item.model_version}
                        </p>
                      </div>
                      <IntelligenceStatus value={item.severity} />
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <div className="mt-3">
                <EmptyState
                  title="No open alerts"
                  description="No open monitoring alerts are visible."
                />
              </div>
            )}
          </div>
        ) : null}
      </div>
    </section>
  );
}
