import type { ReactElement } from "react";

import type { TrainingJobStatus, TrainerKey } from "../../api/aiLifecycle";
import { StatusBadge, type StatusBadgeStatus } from "../StatusBadge";

const metricLabels: Record<string, string> = {
  accuracy: "Accuracy",
  f1_macro: "Macro F1",
  mae: "MAE",
  mse: "MSE",
  precision_macro: "Macro precision",
  r2: "R²",
  recall_macro: "Macro recall",
  rmse: "RMSE",
};

export function JobStatusBadge({
  status,
}: {
  readonly status: TrainingJobStatus;
}): ReactElement {
  const tones: Record<TrainingJobStatus, StatusBadgeStatus> = {
    cancelled: "inactive",
    failed: "critical",
    queued: "warning",
    running: "running",
    succeeded: "healthy",
  };
  return (
    <StatusBadge
      label={status[0].toUpperCase() + status.slice(1)}
      status={tones[status]}
    />
  );
}

export function TrainerLabel({
  trainer,
}: {
  readonly trainer: TrainerKey;
}): ReactElement {
  return (
    <span>
      {trainer.algorithm.replaceAll("_", " ")} · {trainer.task_type}
    </span>
  );
}

export function MetricsGrid({
  metrics,
}: {
  readonly metrics: Record<string, number> | null;
}): ReactElement {
  const entries =
    metrics === null
      ? []
      : Object.entries(metrics).filter(([, value]) => Number.isFinite(value));
  if (entries.length === 0) {
    return <p className="text-sm text-neutral-500">Metrics are not available.</p>;
  }
  return (
    <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {entries.map(([key, value]) => (
        <div
          className="rounded-lg border border-neutral-200 bg-neutral-50 p-4"
          key={key}
        >
          <dt className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
            {metricLabels[key] ?? key.replaceAll("_", " ")}
          </dt>
          <dd className="mt-1 font-mono text-lg font-semibold text-neutral-950">
            {value.toLocaleString(undefined, { maximumFractionDigits: 6 })}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function Notice({ children }: { readonly children: string }): ReactElement {
  return (
    <p className="rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
      {children}
    </p>
  );
}
