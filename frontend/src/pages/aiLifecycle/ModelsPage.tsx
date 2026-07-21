import { useEffect, useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { listTrainingJobs, type TrainingJob } from "../../api/aiLifecycle";
import { useAuth } from "../../auth/useAuth";
import { Notice, TrainerLabel } from "../../components/aiLifecycle/LifecycleUi";
import { PageHeader } from "../../components/ui/PageHeader";
import {
  EmptyState,
  InlineError,
  LoadingSkeleton,
} from "../../components/hierarchy/ResourceStates";
import { formatDate, hierarchyError } from "../hierarchy/shared";

function versionNumber(value: string | null): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : -1;
}

export function ModelsPage(): ReactElement {
  const { role } = useAuth();
  const [jobs, setJobs] = useState<readonly TrainingJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const request =
      role === "operator"
        ? Promise.resolve({ items: [] as readonly TrainingJob[] })
        : listTrainingJobs({
            limit: 100,
            offset: 0,
            signal: controller.signal,
            status: "succeeded",
          });
    request
      .then((page) => setJobs(page.items))
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(hierarchyError(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [revision, role]);
  const models = useMemo(() => {
    const result = new Map<string, TrainingJob>();
    jobs
      .filter((job) => job.registered_model_version !== null)
      .forEach((job) => {
        const current = result.get(job.registered_model_name);
        if (
          current === undefined ||
          versionNumber(job.registered_model_version) >
            versionNumber(current.registered_model_version)
        )
          result.set(job.registered_model_name, job);
      });
    return [...result.values()].sort((a, b) =>
      a.registered_model_name.localeCompare(b.registered_model_name),
    );
  }, [jobs]);
  return (
    <section aria-labelledby="models-heading">
      <PageHeader
        description="Inspect registered models produced by authorized completed training jobs."
        eyebrow="Model governance"
        headingId="models-heading"
        title="Models"
      />
      <div className="mt-5">
        <Notice>
          This catalog contains models discoverable from training jobs visible to your
          account and may not represent the entire registry.
        </Notice>
      </div>
      <div className="mt-5">
        {loading ? (
          <LoadingSkeleton label="Loading discoverable models" />
        ) : error !== null ? (
          <InlineError
            message={error}
            onRetry={() => {
              setLoading(true);
              setError(null);
              setRevision((value) => value + 1);
            }}
          />
        ) : models.length === 0 ? (
          <EmptyState
            description={
              role === "operator"
                ? "The backend permits operator model lookup but does not expose model-name discovery to operators. Open a known model URL directly."
                : "No visible succeeded training jobs contain registered model versions."
            }
            title="No discoverable models"
          />
        ) : (
          <ul className="grid gap-4 lg:grid-cols-2">
            {models.map((job) => (
              <li
                className="rounded-lg border border-border bg-card p-5"
                key={job.registered_model_name}
              >
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <Link
                      className="font-semibold text-purple-700 hover:underline"
                      to={`/models/${encodeURIComponent(job.registered_model_name)}`}
                    >
                      {job.registered_model_name}
                    </Link>
                    <p className="mt-2 text-sm capitalize text-secondary-foreground">
                      <TrainerLabel trainer={job.trainer_key} />
                    </p>
                  </div>
                  <span className="rounded-md bg-neutral-100 px-2 py-1 text-xs font-semibold">
                    Latest discoverable v{job.registered_model_version}
                  </span>
                </div>
                <p className="mt-4 text-xs text-muted-foreground">
                  Visible training completed{" "}
                  {formatDate(job.finished_at ?? job.created_at)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
