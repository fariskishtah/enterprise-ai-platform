import { useEffect, useState, type ReactElement } from "react";
import { useParams } from "react-router-dom";

import { getAutoMLTrial, type AutoMLTrialDetail } from "../../api/automl";
import {
  AutoMLCard,
  AutoMLStatusBadge,
  KeyValues,
  formatMetric,
} from "../../components/automl/AutoMLUi";
import {
  Breadcrumbs,
  InlineError,
  LoadingSkeleton,
} from "../../components/hierarchy/ResourceStates";
import { PageHeader } from "../../components/ui/PageHeader";
import { formatDate, hierarchyError } from "../hierarchy/shared";

export function AutoMLTrialDetailPage(): ReactElement {
  const { studyId = "", trialId = "" } = useParams();
  const [trial, setTrial] = useState<AutoMLTrialDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getAutoMLTrial(studyId, trialId, controller.signal)
      .then(setTrial)
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(hierarchyError(caught));
      });
    return () => controller.abort();
  }, [revision, studyId, trialId]);
  if (error !== null)
    return (
      <InlineError
        message={error}
        onRetry={() => {
          setError(null);
          setRevision((value) => value + 1);
        }}
      />
    );
  if (trial === null) return <LoadingSkeleton label="Loading AutoML trial" />;
  return (
    <section aria-labelledby="automl-trial-heading">
      <Breadcrumbs
        items={[
          { label: "AutoML Studio", to: "/automl" },
          { label: studyId, to: `/automl/studies/${studyId}` },
          { label: `Trial ${trial.trial_number}` },
        ]}
      />
      <PageHeader
        description={`${trial.plugin_id} · ${trial.trial_id}`}
        eyebrow="AutoML trial"
        headingId="automl-trial-heading"
        title={`Trial ${trial.trial_number}`}
      />
      <div className="mt-6 space-y-5">
        <AutoMLCard>
          <KeyValues
            values={[
              { label: "Status", value: <AutoMLStatusBadge status={trial.status} /> },
              { label: "Plugin", value: trial.plugin_id },
              {
                label: "Primary metric",
                value: formatMetric(trial.primary_metric_value),
              },
              {
                label: "Duration",
                value:
                  trial.duration_seconds === null
                    ? "Not available"
                    : `${trial.duration_seconds.toFixed(3)}s`,
              },
              {
                label: "Attempts",
                value: `${trial.attempt_count} / ${trial.max_attempts}`,
              },
              { label: "Created", value: formatDate(trial.created_at) },
              {
                label: "Started",
                value:
                  trial.started_at === null
                    ? "Not started"
                    : formatDate(trial.started_at),
              },
              {
                label: "Finished",
                value:
                  trial.finished_at === null
                    ? "Not finished"
                    : formatDate(trial.finished_at),
              },
            ]}
          />
        </AutoMLCard>
        {trial.safe_error_message === null ? null : (
          <div
            className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800"
            role="alert"
          >
            <strong>Trial did not complete successfully.</strong>
            {trial.error_code === null ? null : (
              <p className="mt-1 font-mono text-xs">Code: {trial.error_code}</p>
            )}
            <p className="mt-1">{trial.safe_error_message}</p>
            {trial.status === "cancelled" ? (
              <p className="mt-1">
                The trial was cancelled before metrics were persisted.
              </p>
            ) : null}
          </div>
        )}
        <MetricTable
          caption="Aggregate metrics"
          rows={trial.aggregate_metrics === null ? [] : [trial.aggregate_metrics]}
        />
        <MetricTable caption="Fold-level metrics" rows={trial.fold_metrics ?? []} />
        <AutoMLCard>
          <h2 className="text-lg font-semibold">Parameters</h2>
          <dl className="mt-4 grid gap-3 sm:grid-cols-2">
            {Object.entries(trial.parameters).map(([key, value]) => (
              <div className="rounded border border-border bg-secondary p-3" key={key}>
                <dt className="text-xs font-semibold uppercase text-muted-foreground">
                  {key.replaceAll("_", " ")}
                </dt>
                <dd className="mt-1 break-words font-mono text-sm">{String(value)}</dd>
              </div>
            ))}
          </dl>
        </AutoMLCard>
      </div>
    </section>
  );
}

function MetricTable({
  caption,
  rows,
}: {
  readonly caption: string;
  readonly rows: readonly Readonly<Record<string, number>>[];
}): ReactElement {
  const keys = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  return (
    <AutoMLCard>
      <h2 className="text-lg font-semibold">{caption}</h2>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">No metrics are available.</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full divide-y divide-border text-left text-sm">
            <caption className="sr-only">{caption}</caption>
            <thead className="bg-muted">
              <tr>
                <th className="px-3 py-2">{rows.length > 1 ? "Fold" : "Summary"}</th>
                {keys.map((key) => (
                  <th className="px-3 py-2" key={key}>
                    {key.replaceAll("_", " ")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((row, index) => (
                <tr key={index}>
                  <th className="px-3 py-2">
                    {rows.length > 1 ? index + 1 : "Aggregate"}
                  </th>
                  {keys.map((key) => (
                    <td className="px-3 py-2 font-mono" key={key}>
                      {formatMetric(row[key] ?? null)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </AutoMLCard>
  );
}
