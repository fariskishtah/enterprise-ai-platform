import type { ReactElement } from "react";
import { Link } from "react-router-dom";

import type { UploadJob } from "../../api/sensorData";
import { StatusBadge, type StatusBadgeStatus } from "../StatusBadge";

function statusStyle(status: UploadJob["status"]): StatusBadgeStatus {
  return {
    COMPLETED: "healthy",
    FAILED: "critical",
    PENDING: "inactive",
    PROCESSING: "running",
  }[status] as StatusBadgeStatus;
}

function formatDate(value: string | null): string {
  if (value === null) return "Not available";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function UploadJobSummary({
  compact = false,
  job,
}: {
  readonly compact?: boolean;
  readonly job: UploadJob;
}): ReactElement {
  return (
    <article className="relative overflow-hidden rounded-lg border border-neutral-200 bg-white p-5 shadow-panel">
      <span
        aria-hidden="true"
        className={`absolute inset-y-0 left-0 w-1 ${job.status === "FAILED" ? "bg-red-600" : job.status === "COMPLETED" ? "bg-emerald-600" : job.status === "PROCESSING" ? "bg-blue-600" : "bg-neutral-400"}`}
      />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-semibold text-neutral-950">{job.filename}</p>
          <p className="mt-1 text-xs text-neutral-500">
            Created {formatDate(job.created_at)}
          </p>
        </div>
        <StatusBadge label={job.status} status={statusStyle(job.status)} />
      </div>
      <dl className={`mt-4 grid gap-3 ${compact ? "grid-cols-3" : "sm:grid-cols-3"}`}>
        <div>
          <dt className="text-xs font-medium text-neutral-500">Total rows</dt>
          <dd className="mt-1 font-semibold">{job.total_rows}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-neutral-500">Valid rows</dt>
          <dd className="mt-1 font-semibold text-emerald-700">{job.valid_rows}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-neutral-500">Invalid rows</dt>
          <dd className="mt-1 font-semibold text-red-700">{job.invalid_rows}</dd>
        </div>
      </dl>
      {compact ? null : (
        <dl className="mt-4 grid gap-3 border-t border-neutral-200 pt-4 sm:grid-cols-2">
          <div>
            <dt className="text-xs font-medium text-neutral-500">Started</dt>
            <dd className="mt-1 text-sm">{formatDate(job.started_at)}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-neutral-500">Finished</dt>
            <dd className="mt-1 text-sm">{formatDate(job.finished_at)}</dd>
          </div>
        </dl>
      )}
      <Link
        className="mt-4 inline-flex text-sm font-semibold text-purple-700 hover:underline"
        to={`/sensor-data/uploads/${job.id}`}
      >
        View upload details
      </Link>
    </article>
  );
}
