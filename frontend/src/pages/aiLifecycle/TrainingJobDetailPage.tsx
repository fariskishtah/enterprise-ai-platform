import { useCallback, useEffect, useRef, useState, type ReactElement } from "react";
import { Link, Navigate, useLocation, useParams } from "react-router-dom";

import {
  cancelTrainingJob,
  getTrainingJob,
  type TrainingJob,
} from "../../api/aiLifecycle";
import { useAuth } from "../../auth/useAuth";
import {
  JobStatusBadge,
  MetricsGrid,
  TrainerLabel,
} from "../../components/aiLifecycle/LifecycleUi";
import { Dialog } from "../../components/hierarchy/Dialogs";
import {
  Breadcrumbs,
  InlineError,
  LoadingSkeleton,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { formatDate, hierarchyError } from "../hierarchy/shared";

const terminal = new Set(["succeeded", "failed", "cancelled"]);
const date = (value: string | null): string =>
  value === null ? "Not available" : formatDate(value);

export function TrainingJobDetailPage(): ReactElement {
  const { role } = useAuth();
  const { trainingJobId = "" } = useParams();
  const location = useLocation();
  const [job, setJob] = useState<TrainingJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const requestActive = useRef(false);
  const jobRef = useRef<TrainingJob | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal, polling = false): Promise<void> => {
      if (requestActive.current) return;
      requestActive.current = true;
      try {
        const result = await getTrainingJob(trainingJobId, signal);
        jobRef.current = result;
        setJob(result);
        setError(null);
        setPollError(null);
      } catch (caught) {
        if (!signal?.aborted) {
          const message = hierarchyError(caught);
          if (polling && jobRef.current !== null) setPollError(message);
          else setError(message);
        }
      } finally {
        requestActive.current = false;
        setLoading(false);
      }
    },
    [trainingJobId],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void load(controller.signal), 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [load]);
  useEffect(() => {
    if (job === null || terminal.has(job.status)) return;
    const timer = window.setInterval(() => void load(undefined, true), 5000);
    return () => window.clearInterval(timer);
  }, [job, load]);
  if (role === "operator") return <Navigate replace to="/" />;
  if (loading && job === null) return <LoadingSkeleton label="Loading training job" />;
  if (error !== null && job === null)
    return (
      <InlineError
        message={error}
        onRetry={() => {
          setLoading(true);
          void load();
        }}
      />
    );
  if (job === null)
    return (
      <InlineError message="Training job was not found." onRetry={() => void load()} />
    );
  const notice = (location.state as { notice?: string } | null)?.notice;
  return (
    <section aria-labelledby="job-heading">
      <Breadcrumbs
        items={[{ label: "Training jobs", to: "/training" }, { label: job.job_id }]}
      />
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-neutral-200 pb-6">
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-purple-700">
            Training execution
          </p>
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-semibold" id="job-heading">
              Training job
            </h2>
            <JobStatusBadge status={job.status} />
          </div>
          <p className="mt-2 break-all font-mono text-xs text-neutral-600">
            {job.job_id}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            className={secondaryButtonClassName}
            onClick={() => void load()}
            type="button"
          >
            Refresh
          </button>
          {job.status === "queued" ? (
            <button
              className="rounded-md bg-red-700 px-4 py-2 text-sm font-semibold text-white"
              onClick={() => setConfirmCancel(true)}
              type="button"
            >
              Cancel queued job
            </button>
          ) : null}
        </div>
      </div>
      {notice ? (
        <p
          className="mt-5 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800"
          role="status"
        >
          {notice}
        </p>
      ) : null}
      {pollError ? (
        <p
          className="mt-5 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
          role="status"
        >
          Automatic refresh failed; showing the last loaded status. {pollError}
        </p>
      ) : null}
      {!terminal.has(job.status) ? (
        <div className="mt-5 rounded-lg border border-blue-200 bg-blue-50 p-4">
          <p className="font-semibold text-blue-950">
            {job.status === "queued" ? "Queued for a worker" : "Training is running"}
          </p>
          <p className="mt-1 text-sm text-blue-800">
            Status refreshes every 5 seconds. No percentage progress is exposed by the
            API.
          </p>
        </div>
      ) : null}
      {job.safe_error_message || job.error_code ? (
        <div
          className="mt-5 rounded-lg border border-red-200 bg-red-50 p-4"
          role="alert"
        >
          <h3 className="font-semibold text-red-900">Training did not complete</h3>
          <p className="mt-1 text-sm text-red-800">
            {job.safe_error_message ?? "The worker returned a safe failure code."}
          </p>
          {job.error_code ? (
            <p className="mt-2 font-mono text-xs text-red-700">
              Code: {job.error_code}
            </p>
          ) : null}
        </div>
      ) : null}
      <dl className="mt-6 grid gap-4 rounded-lg border border-neutral-200 bg-white p-5 sm:grid-cols-2 lg:grid-cols-3">
        {[
          ["Trainer", <TrainerLabel trainer={job.trainer_key} />],
          ["Requested by", job.requested_by_user_id],
          ["Created", formatDate(job.created_at)],
          ["Started", date(job.started_at)],
          ["Finished", date(job.finished_at)],
          ["Attempts", `${job.attempt_count} / ${job.max_attempts}`],
          ["Registered model", job.registered_model_name],
          ["Model version", job.registered_model_version ?? "Not available"],
          ["MLflow experiment", job.mlflow_experiment_id ?? "Not available"],
          ["MLflow run", job.mlflow_run_id ?? "Not available"],
        ].map(([label, value]) => (
          <div key={String(label)}>
            <dt className="text-xs font-semibold uppercase text-neutral-500">
              {label}
            </dt>
            <dd className="mt-1 break-all text-sm text-neutral-900">{value}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-8">
        <h3 className="mb-4 text-lg font-semibold">Metrics and results</h3>
        <MetricsGrid metrics={job.metrics} />
        {job.status === "succeeded" && job.registered_model_version ? (
          <div className="mt-5 flex flex-wrap gap-4">
            <Link
              className="font-semibold text-purple-700 hover:underline"
              to={`/models/${encodeURIComponent(job.registered_model_name)}/versions/${encodeURIComponent(job.registered_model_version)}`}
            >
              Open resulting model version
            </Link>
            <Link
              className="font-semibold text-purple-700 hover:underline"
              to={`/evaluations/jobs/${job.job_id}`}
            >
              Open held-out evaluation
            </Link>
          </div>
        ) : null}
      </div>
      {confirmCancel ? (
        <Dialog
          description="Cancellation is supported only before a worker claims the queued job."
          onClose={() => setConfirmCancel(false)}
          title="Cancel training job?"
        >
          <p className="break-all font-mono text-xs">{job.job_id}</p>
          {cancelError ? (
            <p
              className="mt-4 rounded-md bg-red-50 p-3 text-sm text-red-800"
              role="alert"
            >
              {cancelError}
            </p>
          ) : null}
          <div className="mt-6 flex justify-end gap-3">
            <button
              className={secondaryButtonClassName}
              disabled={cancelBusy}
              onClick={() => setConfirmCancel(false)}
              type="button"
            >
              Keep job
            </button>
            <button
              className="rounded-md bg-red-700 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed"
              disabled={cancelBusy}
              onClick={() => {
                setCancelBusy(true);
                setCancelError(null);
                cancelTrainingJob(job.job_id)
                  .then((result) => {
                    jobRef.current = result;
                    setJob(result);
                    setConfirmCancel(false);
                  })
                  .catch((caught: unknown) => setCancelError(hierarchyError(caught)))
                  .finally(() => setCancelBusy(false));
              }}
              type="button"
            >
              {cancelBusy ? "Cancelling…" : "Cancel queued job"}
            </button>
          </div>
        </Dialog>
      ) : null}
    </section>
  );
}
