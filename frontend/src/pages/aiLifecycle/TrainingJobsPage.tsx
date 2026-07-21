import { useEffect, useState, type ReactElement } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import {
  listTrainingJobs,
  type TrainingJobPage,
  type TrainingJobStatus,
} from "../../api/aiLifecycle";
import { useAuth } from "../../auth/useAuth";
import { JobStatusBadge, TrainerLabel } from "../../components/aiLifecycle/LifecycleUi";
import { TrainingJobFormDialog } from "../../components/aiLifecycle/TrainingJobFormDialog";
import { PageHeader } from "../../components/ui/PageHeader";
import {
  EmptyState,
  InlineError,
  LoadingSkeleton,
  PaginationControls,
  primaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { formatDate, hierarchyError } from "../hierarchy/shared";

const PAGE_SIZE = 20;
const statuses: readonly TrainingJobStatus[] = [
  "queued",
  "running",
  "succeeded",
  "failed",
  "cancelled",
];

export function TrainingJobsPage(): ReactElement {
  const { role } = useAuth();
  const navigate = useNavigate();
  const [page, setPage] = useState<TrainingJobPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState<TrainingJobStatus | "">("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    listTrainingJobs({
      limit: PAGE_SIZE,
      offset,
      signal: controller.signal,
      status: status || undefined,
    })
      .then(setPage)
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(hierarchyError(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [offset, revision, status]);

  if (role === "operator") return <Navigate replace to="/" />;
  const reload = (): void => setRevision((value) => value + 1);
  return (
    <section aria-labelledby="training-heading">
      <PageHeader
        actions={
          <button
            className={primaryButtonClassName}
            onClick={() => setCreating(true)}
            type="button"
          >
            Create training job
          </button>
        }
        description={
          <>
            Submit and follow authorized background Random Forest training.
            {role === "engineer" ? (
              <span className="mt-1 block text-xs text-muted-foreground">
                Engineers see only jobs they requested.
              </span>
            ) : null}
          </>
        }
        eyebrow="AI lifecycle"
        headingId="training-heading"
        title="Training jobs"
      />
      <div className="mt-6 flex items-end gap-3">
        <div>
          <label className="block text-sm font-medium" htmlFor="training-status">
            Status
          </label>
          <select
            className="mt-1 rounded-md border border-border-strong px-3 py-2 text-sm text-foreground"
            id="training-status"
            onChange={(event) => {
              setLoading(true);
              setError(null);
              setOffset(0);
              setStatus(event.target.value as TrainingJobStatus | "");
            }}
            value={status}
          >
            <option value="">All statuses</option>
            {statuses.map((value) => (
              <option key={value} value={value}>
                {value[0].toUpperCase() + value.slice(1)}
              </option>
            ))}
          </select>
        </div>
        <button
          className="rounded-md border border-border-strong bg-elevated px-3 py-2 text-sm font-semibold text-secondary-foreground"
          onClick={() => {
            setLoading(true);
            setError(null);
            reload();
          }}
          type="button"
        >
          Refresh
        </button>
      </div>
      <div className="mt-5">
        {loading ? (
          <LoadingSkeleton label="Loading training jobs" />
        ) : error !== null ? (
          <InlineError message={error} onRetry={reload} />
        ) : page === null || page.total === 0 ? (
          <EmptyState
            action={
              <button
                className={primaryButtonClassName}
                onClick={() => setCreating(true)}
                type="button"
              >
                Create training job
              </button>
            }
            description="No authorized training jobs match this status."
            title="No training jobs"
          />
        ) : (
          <>
            <div className="overflow-x-auto rounded-lg border border-border bg-card">
              <table className="min-w-full divide-y divide-neutral-200 text-left text-sm">
                <thead className="bg-muted text-xs uppercase text-secondary-foreground">
                  <tr>
                    <th className="px-4 py-3">Job</th>
                    <th className="px-4 py-3">Trainer</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Model</th>
                    <th className="px-4 py-3">Created</th>
                    <th className="px-4 py-3">Attempts</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-100">
                  {page.items.map((job) => (
                    <tr key={job.job_id}>
                      <td className="px-4 py-3">
                        <Link
                          className="font-mono text-xs font-semibold text-purple-700 hover:underline"
                          to={`/training/${job.job_id}`}
                        >
                          {job.job_id}
                        </Link>
                      </td>
                      <td className="px-4 py-3 capitalize">
                        <TrainerLabel trainer={job.trainer_key} />
                      </td>
                      <td className="px-4 py-3">
                        <JobStatusBadge status={job.status} />
                      </td>
                      <td className="px-4 py-3">
                        <span className="font-medium">{job.registered_model_name}</span>
                        <br />
                        <span className="text-xs text-muted-foreground">
                          Version {job.registered_model_version ?? "pending"}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        {formatDate(job.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        {job.attempt_count} / {job.max_attempts}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <PaginationControls
              limit={page.limit}
              offset={page.offset}
              onPageChange={setOffset}
              total={page.total}
            />
          </>
        )}
      </div>
      {creating ? (
        <TrainingJobFormDialog
          onClose={() => setCreating(false)}
          onCreated={(id) =>
            navigate(`/training/${id}`, {
              state: { notice: "Training job submitted." },
            })
          }
        />
      ) : null}
    </section>
  );
}
