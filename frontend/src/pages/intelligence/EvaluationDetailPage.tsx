import { useEffect, useState, type ReactElement } from "react";
import { Link, useParams } from "react-router-dom";
import { getEvaluation, type MonitoringEvaluation } from "../../api/monitoring";
import {
  InlineError,
  LoadingSkeleton,
} from "../../components/hierarchy/ResourceStates";
import {
  IntelligenceStatus,
  KeyValues,
  formatDate,
  panelClassName,
} from "../../components/intelligence/IntelligenceUi";
import { PageHeader } from "../../components/ui/PageHeader";
import { isRequestCancelled } from "../../api/client";
export function EvaluationDetailPage(): ReactElement {
  const { id = "" } = useParams<{ id: string }>();
  const [item, setItem] = useState<MonitoringEvaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const c = new AbortController();
    let active = true;
    getEvaluation(id, c.signal)
      .then((value) => {
        if (active) {
          setItem(value);
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (active && !isRequestCancelled(e, c.signal))
          setError(e instanceof Error ? e.message : "Evaluation unavailable.");
      });
    return () => {
      active = false;
      c.abort();
    };
  }, [id]);
  if (error) return <InlineError message={error} onRetry={() => location.reload()} />;
  if (!item) return <LoadingSkeleton />;
  return (
    <section>
      <PageHeader
        eyebrow="Monitoring evaluation"
        headingId="evaluation-heading"
        title={item.id}
        description={`${item.registered_model_name} · version ${item.model_version}`}
        actions={<IntelligenceStatus value={item.overall_status} />}
      />
      <div className="mt-6">
        <KeyValues
          items={[
            {
              label: "Window",
              value: `${formatDate(item.window_start)} — ${formatDate(item.window_end)}`,
            },
            { label: "Samples", value: item.evaluated_sample_count },
            {
              label: "Successful predictions",
              value: item.successful_prediction_count,
            },
            { label: "Failed predictions", value: item.failed_prediction_count },
            { label: "Trigger", value: item.trigger },
            { label: "Created", value: formatDate(item.created_at) },
          ]}
        />
      </div>
      <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ["Data quality", item.data_quality_status],
          ["Feature drift", item.feature_drift_status],
          ["Prediction drift", item.prediction_drift_status],
          ["Operations", item.operational_health_status],
        ].map(([label, value]) => (
          <div className={panelClassName} key={label}>
            <p className="mb-2 text-sm font-semibold text-foreground">{label}</p>
            <IntelligenceStatus value={value} />
          </div>
        ))}
      </div>
      <div className="mt-6 flex flex-wrap gap-4">
        <Link
          className="font-semibold text-link"
          to={`/monitoring/models/${encodeURIComponent(item.registered_model_name)}/versions/${encodeURIComponent(item.model_version)}`}
        >
          Exact-version monitoring
        </Link>
      </div>
      <div className={`${panelClassName} mt-6`}>
        <h2 className="text-lg font-semibold text-foreground">Persisted report</h2>
        <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap text-xs text-secondary-foreground">
          {JSON.stringify(item.report, null, 2)}
        </pre>
      </div>
    </section>
  );
}
