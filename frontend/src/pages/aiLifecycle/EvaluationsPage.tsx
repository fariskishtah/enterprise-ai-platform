import { useEffect, useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import {
  listTrainingJobs,
  type TrainingJob,
  type TrainingTask,
} from "../../api/aiLifecycle";
import { PageHeader } from "../../components/ui/PageHeader";
import {
  EmptyState,
  InlineError,
  LoadingSkeleton,
} from "../../components/hierarchy/ResourceStates";

export function EvaluationsPage(): ReactElement {
  const [jobs, setJobs] = useState<readonly TrainingJob[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [task, setTask] = useState<TrainingTask>("classification");
  const [algorithm, setAlgorithm] = useState("");
  const [primaryMetric, setPrimaryMetric] = useState("accuracy");

  useEffect(() => {
    const controller = new AbortController();
    listTrainingJobs({
      limit: 100,
      offset: 0,
      status: "succeeded",
      signal: controller.signal,
    })
      .then((page) => setJobs(page.items))
      .catch((caught: unknown) => {
        if (!controller.signal.aborted)
          setError(
            caught instanceof Error ? caught.message : "Unable to load evaluations.",
          );
      });
    return () => controller.abort();
  }, []);

  const algorithms = useMemo(
    () => [...new Set((jobs ?? []).map((job) => job.trainer_key.algorithm))].sort(),
    [jobs],
  );
  const visible = (jobs ?? [])
    .filter(
      (job) =>
        job.trainer_key.task_type === task &&
        (!algorithm || job.trainer_key.algorithm === algorithm),
    )
    .sort((left, right) => {
      const leftValue = left.metrics?.[primaryMetric];
      const rightValue = right.metrics?.[primaryMetric];
      if (leftValue === undefined) return 1;
      if (rightValue === undefined) return -1;
      return ["mae", "mse", "rmse", "mape", "median_absolute_error"].includes(
        primaryMetric,
      )
        ? leftValue - rightValue
        : rightValue - leftValue;
    });

  return (
    <div className="space-y-6">
      <PageHeader
        description="Compare compatible completed training runs and inspect real held-out metrics, plots, and global explanations."
        eyebrow="AI lifecycle"
        headingId="evaluation-studio-heading"
        title="Evaluation Studio"
      />
      <section className="grid gap-3 rounded-lg border border-border bg-card p-4 sm:grid-cols-3">
        <label className="text-sm font-medium">
          Task
          <select
            className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2"
            onChange={(event) => {
              const next = event.target.value as TrainingTask;
              setTask(next);
              setPrimaryMetric(next === "classification" ? "accuracy" : "rmse");
            }}
            value={task}
          >
            <option value="classification">Classification</option>
            <option value="regression">Regression</option>
          </select>
        </label>
        <label className="text-sm font-medium">
          Primary metric
          <select
            className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2"
            onChange={(event) => setPrimaryMetric(event.target.value)}
            value={primaryMetric}
          >
            {(task === "classification"
              ? ["accuracy", "precision_macro", "recall_macro", "f1_macro"]
              : ["rmse", "mae", "mse", "r2", "mape", "median_absolute_error"]
            ).map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium">
          Algorithm
          <select
            className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2"
            onChange={(event) => setAlgorithm(event.target.value)}
            value={algorithm}
          >
            <option value="">All algorithms</option>
            {algorithms.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
      </section>
      {error ? (
        <InlineError message={error} onRetry={() => window.location.reload()} />
      ) : jobs === null ? (
        <LoadingSkeleton label="Loading evaluated models" />
      ) : visible.length === 0 ? (
        <EmptyState
          title="No evaluated models"
          description="Completed training jobs with registered versions will appear here."
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-muted text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Model</th>
                <th className="px-4 py-3">Task</th>
                <th className="px-4 py-3">Algorithm</th>
                <th className="px-4 py-3">Primary metric</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3">Evaluation</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {visible.map((job, index) => {
                return (
                  <tr key={job.job_id} className="hover:bg-muted">
                    <td className="px-4 py-3 font-medium">
                      {index + 1}. {job.registered_model_name} v
                      {job.registered_model_version}
                    </td>
                    <td className="px-4 py-3">{job.trainer_key.task_type}</td>
                    <td className="px-4 py-3">{job.trainer_key.algorithm}</td>
                    <td className="px-4 py-3">
                      {primaryMetric}: {job.metrics?.[primaryMetric]?.toFixed(4) ?? "—"}
                    </td>
                    <td className="px-4 py-3">
                      {new Date(job.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3">
                      <Link
                        className="font-medium text-primary hover:underline"
                        to={`/evaluations/jobs/${job.job_id}`}
                      >
                        Open
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-sm text-muted-foreground">
        Rankings are intentionally not combined across classification and regression
        tasks. Dataset-context comparison is limited to the metadata available on each
        training job.
      </p>
    </div>
  );
}
