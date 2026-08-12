import { useEffect, useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { listTrainingJobs, type TrainingJob } from "../api/aiLifecycle";
import { listFactories, type Factory } from "../api/hierarchy";
import { listUploadJobs, type UploadJob } from "../api/sensorData";
import { hasProductCapability } from "../auth/permissions";
import { useAuth } from "../auth/useAuth";
import { StatusBadge, type StatusBadgeStatus } from "../components/StatusBadge";
import { InlineError, LoadingSkeleton } from "../components/hierarchy/ResourceStates";
import { PageHeader } from "../components/ui/PageHeader";

interface DashboardData {
  readonly factories: readonly Factory[];
  readonly factoryTotal: number;
  readonly trainingJobs: readonly TrainingJob[];
  readonly trainingTotal: number;
  readonly uploads: readonly UploadJob[];
  readonly uploadTotal: number;
}

const statusTone = (status: string): StatusBadgeStatus => {
  if (["COMPLETED", "succeeded"].includes(status)) return "healthy";
  if (["FAILED", "failed"].includes(status)) return "critical";
  if (["PROCESSING", "running"].includes(status)) return "running";
  if (["PENDING", "queued"].includes(status)) return "inactive";
  return "inactive";
};

function GettingStarted({
  canManageAi,
  canManageFactories,
}: {
  readonly canManageAi: boolean;
  readonly canManageFactories: boolean;
}): ReactElement {
  return (
    <section className="mt-7 rounded-lg border border-purple-200 bg-purple-50 p-5 text-neutral-950 shadow-panel sm:p-6">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-purple-800">
        Start here
      </p>
      <h2 className="mt-2 text-xl font-semibold">Build your workspace step by step</h2>
      <p className="mt-2 max-w-3xl text-sm text-neutral-700">
        FactoryMind becomes useful as you add real manufacturing context. Complete one
        step at a time; advanced AI tools can wait until your data is ready.
      </p>
      <ol className="mt-5 grid gap-3 lg:grid-cols-3">
        <li className="rounded-md border border-purple-200 bg-white p-4">
          <p className="text-xs font-semibold uppercase text-purple-800">1 · Factory</p>
          <p className="mt-2 font-semibold">Add your site and equipment</p>
          <p className="mt-1 text-sm text-neutral-600">
            Organize the factory, machines, and sensors your team works with.
          </p>
          {canManageFactories ? (
            <Link
              className="mt-3 inline-block text-sm font-semibold text-purple-800"
              to="/factories"
            >
              Set up the first factory
            </Link>
          ) : null}
        </li>
        <li className="rounded-md border border-purple-200 bg-white p-4">
          <p className="text-xs font-semibold uppercase text-purple-800">2 · Data</p>
          <p className="mt-2 font-semibold">Bring in trusted data</p>
          <p className="mt-1 text-sm text-neutral-600">
            Upload machine readings or documents and check their quality.
          </p>
          {canManageAi ? (
            <Link
              className="mt-3 inline-block text-sm font-semibold text-purple-800"
              to="/sensor-data/onboarding"
            >
              Open data onboarding
            </Link>
          ) : null}
        </li>
        <li className="rounded-md border border-purple-200 bg-white p-4">
          <p className="text-xs font-semibold uppercase text-purple-800">3 · Insight</p>
          <p className="mt-2 font-semibold">Use guided, grounded AI</p>
          <p className="mt-1 text-sm text-neutral-600">
            Start with guided workflows before opening advanced model tools.
          </p>
          {canManageAi ? (
            <Link
              className="mt-3 inline-block text-sm font-semibold text-purple-800"
              to="/guided-ai"
            >
              Explore Guided AI
            </Link>
          ) : null}
        </li>
      </ol>
    </section>
  );
}

function MetricCard({
  label,
  value,
}: {
  readonly label: string;
  readonly value: number;
}): ReactElement {
  return (
    <article className="rounded-lg border border-border bg-card p-5 shadow-panel">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </p>
      <p className="mt-3 text-3xl font-semibold tracking-tight text-foreground">
        {value.toLocaleString()}
      </p>
    </article>
  );
}

export function Dashboard(): ReactElement {
  const { role } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const canReadEngineering = hasProductCapability(role, "engineering.read");
  const canWriteEngineering = hasProductCapability(role, "engineering.write");
  const canManageWorkspace = hasProductCapability(role, "tenant.administer");
  const engineeringPersona = role === "engineer" || role === "analyst";
  const ownerPersona = role === "owner";

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const emptyTraining = { items: [], limit: 12, offset: 0, total: 0 };
    const emptyUploads = { items: [], limit: 12, offset: 0, total: 0 };
    Promise.all([
      listFactories({ limit: 12, signal: controller.signal }),
      canReadEngineering
        ? listTrainingJobs({ limit: 12, offset: 0, signal: controller.signal })
        : Promise.resolve(emptyTraining),
      canReadEngineering
        ? listUploadJobs({ limit: 12, signal: controller.signal })
        : Promise.resolve(emptyUploads),
    ])
      .then(([factories, training, uploads]) => {
        if (active) {
          setData({
            factories: factories.items,
            factoryTotal: factories.total,
            trainingJobs: training.items,
            trainingTotal: training.total,
            uploads: uploads.items,
            uploadTotal: uploads.total,
          });
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (active)
          setError(
            caught instanceof Error ? caught.message : "Dashboard data is unavailable.",
          );
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [canReadEngineering, revision]);

  const models = useMemo(
    () =>
      new Set(
        data?.trainingJobs
          .filter((job) => job.registered_model_version !== null)
          .map((job) => job.registered_model_name),
      ).size,
    [data],
  );
  const activity = useMemo(() => {
    if (data === null) return [];
    return [
      ...data.uploads.map((job) => ({
        id: job.id,
        label: job.filename,
        status: job.status,
        timestamp: job.created_at,
        type: "Upload",
      })),
      ...data.trainingJobs.map((job) => ({
        id: job.job_id,
        label: job.registered_model_name,
        status: job.status,
        timestamp: job.created_at,
        type: "Training",
      })),
    ]
      .sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp))
      .slice(0, 6);
  }, [data]);

  if (error !== null)
    return (
      <InlineError message={error} onRetry={() => setRevision((value) => value + 1)} />
    );
  if (data === null) return <LoadingSkeleton label="Loading operations dashboard" />;

  const trainingCounts = data.trainingJobs.reduce<Record<string, number>>(
    (counts, job) => {
      counts[job.status] = (counts[job.status] ?? 0) + 1;
      return counts;
    },
    {},
  );
  const maxStatus = Math.max(1, ...Object.values(trainingCounts));

  return (
    <section aria-labelledby="dashboard-heading">
      <PageHeader
        actions={<StatusBadge label="Platform healthy" status="healthy" />}
        description={
          engineeringPersona
            ? "Prepare trusted factory data, review AI work, and open advanced tools when the workflow requires them."
            : "See your factories and move to the next setup, team, data, or plan task from one place."
        }
        eyebrow={
          engineeringPersona ? "Engineering and data" : "Your manufacturing workspace"
        }
        headingId="dashboard-heading"
        title={engineeringPersona ? "Data & AI workspace" : "Factory overview"}
      />

      {data.factoryTotal === 0 ? (
        <GettingStarted
          canManageAi={canWriteEngineering}
          canManageFactories={canWriteEngineering}
        />
      ) : null}

      <div className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Visible factories" value={data.factoryTotal} />
        {canReadEngineering ? (
          <MetricCard label="Recent data imports" value={data.uploadTotal} />
        ) : null}
        {engineeringPersona ? (
          <MetricCard label="Model training runs" value={data.trainingTotal} />
        ) : null}
        {engineeringPersona ? (
          <MetricCard label="Available AI models" value={models} />
        ) : null}
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(18rem,0.65fr)]">
        <article className="rounded-lg border border-border bg-card p-5 shadow-panel sm:p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-widest text-eyebrow">
                Operational portfolio
              </p>
              <h2 className="mt-2 text-xl font-semibold text-foreground">
                Authorized factories
              </h2>
            </div>
            <Link
              className="text-sm font-semibold text-link hover:text-purple-400"
              to="/factories"
            >
              Open hierarchy
            </Link>
          </div>
          {data.factories.length === 0 ? (
            <div className="mt-8 rounded-md bg-elevated p-5">
              <p className="font-semibold text-foreground">No factories yet</p>
              <p className="mt-1 text-sm text-secondary-foreground">
                {canWriteEngineering
                  ? "Set up the first factory to organize production assets, machines, and sensor data."
                  : "Ask a workspace owner to add a factory so you can begin exploring operations."}
              </p>
              {canWriteEngineering ? (
                <Link
                  className="mt-4 inline-block text-sm font-semibold text-link"
                  to="/factories"
                >
                  Set up your first factory
                </Link>
              ) : null}
            </div>
          ) : (
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              {data.factories.slice(0, 6).map((factory) => (
                <Link
                  className="rounded-md border border-border bg-elevated p-4 transition hover:border-purple-400 hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-purple-600"
                  key={factory.id}
                  to={`/factories/${factory.id}`}
                >
                  <p className="font-semibold text-foreground">{factory.name}</p>
                  <p className="mt-1 text-sm text-secondary-foreground">
                    {factory.location ?? "Location not recorded"}
                  </p>
                </Link>
              ))}
            </div>
          )}
        </article>

        <article className="rounded-lg border border-border bg-card p-5 shadow-panel sm:p-6">
          <p className="text-xs font-semibold uppercase tracking-widest text-eyebrow">
            Quick actions
          </p>
          <h2 className="mt-2 text-xl font-semibold text-foreground">Continue work</h2>
          <div className="mt-5 grid gap-3">
            <Link
              className="rounded-md bg-purple-700 px-4 py-3 text-center text-sm font-semibold text-inverse hover:bg-purple-800"
              to="/factories"
            >
              {data.factoryTotal === 0 ? "Set up a factory" : "View factories & assets"}
            </Link>
            {canWriteEngineering ? (
              <Link
                className="rounded-md border border-border-strong bg-elevated px-4 py-3 text-center text-sm font-semibold text-secondary-foreground hover:bg-muted"
                to="/sensor-data/onboarding"
              >
                Bring in machine data
              </Link>
            ) : null}
            {ownerPersona && canManageWorkspace ? (
              <Link
                className="rounded-md border border-border-strong bg-elevated px-4 py-3 text-center text-sm font-semibold text-secondary-foreground hover:bg-muted"
                to="/users"
              >
                Manage your team
              </Link>
            ) : null}
            {ownerPersona && canManageWorkspace ? (
              <Link
                className="rounded-md border border-border-strong bg-elevated px-4 py-3 text-center text-sm font-semibold text-secondary-foreground hover:bg-muted"
                to="/settings/billing"
              >
                Review plan & usage
              </Link>
            ) : null}
            {engineeringPersona && canWriteEngineering ? (
              <Link
                className="rounded-md border border-border-strong bg-elevated px-4 py-3 text-center text-sm font-semibold text-secondary-foreground hover:bg-muted"
                to="/knowledge"
              >
                Prepare trusted documents
              </Link>
            ) : null}
            {engineeringPersona && !canWriteEngineering ? (
              <Link
                className="rounded-md border border-border-strong bg-elevated px-4 py-3 text-center text-sm font-semibold text-secondary-foreground hover:bg-muted"
                to="/models"
              >
                Review available models
              </Link>
            ) : null}
          </div>
        </article>
      </div>

      {engineeringPersona ? (
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <article className="rounded-lg border border-border bg-card p-5 shadow-panel sm:p-6">
            <h2 className="text-lg font-semibold text-foreground">Training status</h2>
            <p className="mt-1 text-sm text-secondary-foreground">
              Distribution across the most recent authorized jobs.
            </p>
            {Object.keys(trainingCounts).length === 0 ? (
              <p className="mt-6 rounded-md bg-elevated p-5 text-sm text-secondary-foreground">
                Not enough data. No training jobs are visible.
              </p>
            ) : (
              <div
                aria-label="Training job status distribution"
                className="mt-6 space-y-4"
                role="img"
              >
                {Object.entries(trainingCounts).map(([status, count]) => (
                  <div key={status}>
                    <div className="mb-1.5 flex justify-between text-sm">
                      <span className="capitalize text-secondary-foreground">
                        {status}
                      </span>
                      <strong>{count}</strong>
                    </div>
                    <div className="h-2.5 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-purple-700"
                        style={{ width: `${(count / maxStatus) * 100}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </article>
          <article className="rounded-lg border border-border bg-card p-5 shadow-panel sm:p-6">
            <h2 className="text-lg font-semibold text-foreground">
              Recent operational activity
            </h2>
            {activity.length === 0 ? (
              <p className="mt-6 rounded-md bg-elevated p-5 text-sm text-secondary-foreground">
                No recent upload or training activity is visible.
              </p>
            ) : (
              <ol className="mt-5 divide-y divide-neutral-200">
                {activity.map((item) => (
                  <li
                    className="flex items-center justify-between gap-4 py-3"
                    key={`${item.type}-${item.id}`}
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-foreground">
                        {item.label}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {item.type} · {new Date(item.timestamp).toLocaleString()}
                      </p>
                    </div>
                    <StatusBadge label={item.status} status={statusTone(item.status)} />
                  </li>
                ))}
              </ol>
            )}
          </article>
        </div>
      ) : null}
    </section>
  );
}
