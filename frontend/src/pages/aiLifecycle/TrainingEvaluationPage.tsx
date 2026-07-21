import { useEffect, useState, type ReactElement } from "react";
import { Link, useParams } from "react-router-dom";

import {
  getTrainingEvaluation,
  getTrainingJob,
  type EvaluationPayload,
  type TrainingJob,
} from "../../api/aiLifecycle";
import { PageHeader } from "../../components/ui/PageHeader";
import {
  EmptyState,
  InlineError,
  LoadingSkeleton,
} from "../../components/hierarchy/ResourceStates";

export function TrainingEvaluationPage(): ReactElement {
  const { trainingJobId = "" } = useParams();
  const [data, setData] = useState<{
    job: TrainingJob;
    evaluation: EvaluationPayload;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getTrainingJob(trainingJobId, controller.signal),
      getTrainingEvaluation(trainingJobId, controller.signal),
    ])
      .then(([job, evaluation]) => setData({ job, evaluation }))
      .catch((caught: unknown) => {
        if (!controller.signal.aborted)
          setError(
            caught instanceof Error
              ? caught.message
              : "Unable to load this evaluation.",
          );
      });
    return () => controller.abort();
  }, [trainingJobId]);
  if (error)
    return <InlineError message={error} onRetry={() => window.location.reload()} />;
  if (!data) return <LoadingSkeleton label="Loading held-out evaluation" />;
  const { evaluation, job } = data;
  const confusion = evaluation.plots.confusion_matrix as
    { labels: string[]; values: number[][] } | undefined;
  const actual = evaluation.plots.actual_vs_predicted as
    { actual: number; predicted: number }[] | undefined;
  const importance = evaluation.explainability.permutation_importance as
    | { feature: string; value: number }[]
    | { supported: false; reason: string }
    | undefined;
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Evaluation Studio"
        headingId="training-evaluation-heading"
        title={`${job.registered_model_name} v${job.registered_model_version ?? "—"}`}
        description={`${evaluation.algorithm} · ${evaluation.task_type} · ${evaluation.sample_count} held-out samples · ${evaluation.feature_count} features`}
      />
      <Link
        className="text-sm font-medium text-primary hover:underline"
        to="/evaluations"
      >
        ← Evaluation leaderboard
      </Link>
      <section
        className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
        aria-label="Held-out metrics"
      >
        {Object.entries(evaluation.metrics).map(([name, value]) => (
          <div className="rounded-lg border border-border bg-card p-4" key={name}>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              {name.replaceAll("_", " ")}
            </p>
            <p className="mt-1 text-2xl font-semibold text-foreground">
              {value.toFixed(4)}
            </p>
          </div>
        ))}
      </section>
      {confusion ? (
        <section className="rounded-lg border border-border bg-card p-5">
          <h2 className="text-lg font-semibold">Confusion matrix</h2>
          <div className="mt-4 overflow-x-auto">
            <table className="text-center text-sm">
              <thead>
                <tr>
                  <th className="p-2">Actual \ predicted</th>
                  {confusion.labels.map((label) => (
                    <th className="p-2" key={label}>
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {confusion.values.map((row, index) => (
                  <tr key={confusion.labels[index]}>
                    <th className="p-2">{confusion.labels[index]}</th>
                    {row.map((value, column) => (
                      <td className="border border-border p-3" key={column}>
                        {value}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
      {actual ? (
        <section className="rounded-lg border border-border bg-card p-5">
          <h2 className="text-lg font-semibold">Actual vs predicted</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Deterministically bounded held-out points.
          </p>
          <div className="mt-4 max-h-72 overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className="text-left">Actual</th>
                  <th className="text-left">Predicted</th>
                </tr>
              </thead>
              <tbody>
                {actual.map((point, index) => (
                  <tr key={index}>
                    <td>{point.actual}</td>
                    <td>{point.predicted}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
      <section className="rounded-lg border border-border bg-card p-5">
        <h2 className="text-lg font-semibold">Permutation importance</h2>
        {Array.isArray(importance) ? (
          <ol className="mt-3 space-y-2">
            {importance.map((item) => (
              <li className="flex justify-between gap-4" key={item.feature}>
                <span>{item.feature}</span>
                <span className="font-mono">{item.value.toFixed(5)}</span>
              </li>
            ))}
          </ol>
        ) : (
          <EmptyState
            title="Explanation unavailable"
            description={importance?.reason ?? "No explanation payload was returned."}
          />
        )}
      </section>
      {Object.keys(evaluation.omitted).length ? (
        <section className="rounded-lg border border-border bg-muted p-5">
          <h2 className="font-semibold">Compatibility notes</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {Object.entries(evaluation.omitted).map(([name, reason]) => (
              <li key={name}>
                <strong>{name}:</strong> {reason}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <p className="text-sm text-muted-foreground">
        Explanations describe model behavior and are not causal conclusions. Local
        explanations and SHAP are not available in this milestone.
      </p>
    </div>
  );
}
