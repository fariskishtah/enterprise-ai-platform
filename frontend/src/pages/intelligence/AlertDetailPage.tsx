import { useEffect, useState, type ReactElement } from "react";
import { Link, useParams } from "react-router-dom";
import {
  acknowledgeAlert,
  getAlert,
  resolveAlert,
  type MonitoringAlert,
} from "../../api/alerts";
import { useAuth } from "../../auth/useAuth";
import {
  InlineError,
  LoadingSkeleton,
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import {
  IntelligenceStatus,
  KeyValues,
  formatDate,
  panelClassName,
} from "../../components/intelligence/IntelligenceUi";
import { PageHeader } from "../../components/ui/PageHeader";
import { isRequestCancelled } from "../../api/client";
export function AlertDetailPage(): ReactElement {
  const { id = "" } = useParams<{ id: string }>();
  const { role } = useAuth();
  const [item, setItem] = useState<MonitoringAlert | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (role === "operator") return;
    const c = new AbortController();
    let active = true;
    getAlert(id, c.signal)
      .then((value) => {
        if (active) {
          setItem(value);
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (active && !isRequestCancelled(e, c.signal))
          setError(e instanceof Error ? e.message : "Alert unavailable.");
      });
    return () => {
      active = false;
      c.abort();
    };
  }, [id, revision, role]);
  if (role === "operator")
    return (
      <InlineError
        message="Alert detail is restricted to administrators and engineers."
        onRetry={() => history.back()}
      />
    );
  if (error)
    return (
      <InlineError
        message={error}
        onRetry={() => {
          setError(null);
          setRevision((v) => v + 1);
        }}
      />
    );
  if (!item) return <LoadingSkeleton />;
  const mutate = (action: () => Promise<MonitoringAlert>) => {
    if (!confirm("Confirm this alert action?")) return;
    setBusy(true);
    action()
      .then(setItem)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "Alert action failed."),
      )
      .finally(() => setBusy(false));
  };
  return (
    <section>
      <PageHeader
        eyebrow="Monitoring alert"
        headingId="alert-heading"
        title={item.title}
        description={item.safe_summary}
        actions={
          <div className="flex gap-2">
            <IntelligenceStatus value={item.severity} />
            <IntelligenceStatus value={item.status} />
          </div>
        }
      />
      <div className="mt-6">
        <KeyValues
          items={[
            { label: "Alert type", value: item.alert_type },
            {
              label: "Model/version",
              value: `${item.registered_model_name} / ${item.model_version}`,
            },
            { label: "Occurrences", value: item.occurrence_count },
            { label: "First detected", value: formatDate(item.first_detected_at) },
            { label: "Last detected", value: formatDate(item.last_detected_at) },
            { label: "Acknowledged", value: formatDate(item.acknowledged_at) },
            { label: "Resolved", value: formatDate(item.resolved_at) },
          ]}
        />
      </div>
      <div className={`${panelClassName} mt-6 flex flex-wrap gap-3`}>
        {item.status === "open" ? (
          <button
            disabled={busy}
            className={secondaryButtonClassName}
            onClick={() => mutate(() => acknowledgeAlert(id))}
            type="button"
          >
            Acknowledge
          </button>
        ) : null}
        {role === "admin" && item.status !== "resolved" ? (
          <button
            disabled={busy}
            className={primaryButtonClassName}
            onClick={() => mutate(() => resolveAlert(id))}
            type="button"
          >
            Resolve alert
          </button>
        ) : null}
        {item.monitoring_evaluation_id ? (
          <Link
            className="self-center font-semibold text-link"
            to={`/monitoring/evaluations/${item.monitoring_evaluation_id}`}
          >
            Evaluation context
          </Link>
        ) : null}
        <Link
          className="self-center font-semibold text-link"
          to={`/monitoring/models/${encodeURIComponent(item.registered_model_name)}/versions/${item.model_version}`}
        >
          Model monitoring
        </Link>
      </div>
    </section>
  );
}
