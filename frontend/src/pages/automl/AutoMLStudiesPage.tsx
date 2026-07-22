import { useEffect, useState, type ReactElement, type ReactNode } from "react";
import { Link, Navigate } from "react-router-dom";

import {
  getAutoMLStudy,
  listAutoMLStudies,
  listAutoMLTrials,
  type AutoMLStudyDetail,
  type AutoMLStudyPage,
  type AutoMLStudyStatus,
  type AutoMLTask,
  type AutoMLTrialStatus,
} from "../../api/automl";
import { isRequestCancelled } from "../../api/client";
import { useAuth } from "../../auth/useAuth";
import {
  AutoMLStatusBadge,
  terminalStudyStatuses,
} from "../../components/automl/AutoMLUi";
import {
  EmptyState,
  InlineError,
  LoadingSkeleton,
  PaginationControls,
  primaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { PageHeader } from "../../components/ui/PageHeader";
import { formatDate, hierarchyError } from "../hierarchy/shared";

const PAGE_SIZE = 20;
const POLL_INTERVAL_MS = 5_000;
const statuses: readonly AutoMLStudyStatus[] = [
  "queued",
  "running",
  "succeeded",
  "failed",
  "cancelled",
];

type TrialCounts = Partial<Record<AutoMLTrialStatus, number>>;

export function AutoMLStudiesPage(): ReactElement {
  const { role } = useAuth();
  const [page, setPage] = useState<AutoMLStudyPage | null>(null);
  const [counts, setCounts] = useState<Readonly<Record<string, TrialCounts>>>({});
  const [details, setDetails] = useState<Readonly<Record<string, AutoMLStudyDetail>>>(
    {},
  );
  const [status, setStatus] = useState<AutoMLStudyStatus | "">("");
  const [task, setTask] = useState<AutoMLTask | "">("");
  const [plugin, setPlugin] = useState("");
  const [requester, setRequester] = useState("");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async (): Promise<void> => {
      try {
        const next = await listAutoMLStudies({
          limit: PAGE_SIZE,
          offset,
          pluginId: plugin || undefined,
          requesterId: role === "admin" && requester ? requester : undefined,
          signal: controller.signal,
          status: status || undefined,
          taskType: task || undefined,
        });
        if (controller.signal.aborted) return;
        setPage(next);
        setError(null);
        const progressEntries = await Promise.all(
          next.items.map(async (study) => {
            const [trials, detail] = await Promise.all([
              listAutoMLTrials({
                limit: 100,
                offset: 0,
                signal: controller.signal,
                studyId: study.study_id,
              }),
              getAutoMLStudy(study.study_id, controller.signal),
            ]);
            const trialCounts: TrialCounts = {};
            for (const trial of trials.items) {
              trialCounts[trial.status] = (trialCounts[trial.status] ?? 0) + 1;
            }
            return [study.study_id, trialCounts, detail] as const;
          }),
        );
        if (!controller.signal.aborted) {
          setCounts(
            Object.fromEntries(progressEntries.map(([id, value]) => [id, value])),
          );
          setDetails(
            Object.fromEntries(progressEntries.map(([id, , detail]) => [id, detail])),
          );
        }
        if (next.items.some((study) => !terminalStudyStatuses.has(study.status))) {
          timer = window.setTimeout(() => void load(), POLL_INTERVAL_MS);
        }
      } catch (caught) {
        if (!isRequestCancelled(caught, controller.signal)) {
          setError(hierarchyError(caught));
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    return () => {
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [offset, plugin, requester, revision, role, status, task]);

  if (role === "operator") return <Navigate replace to="/" />;
  const resetPage = (): void => {
    setOffset(0);
    setLoading(true);
    setError(null);
  };
  return (
    <section aria-labelledby="automl-heading">
      <PageHeader
        actions={
          <Link className={primaryButtonClassName} to="/automl/new">
            Create study
          </Link>
        }
        description="Run bounded, deterministic cross-validation studies across approved algorithms."
        eyebrow="AI lifecycle"
        headingId="automl-heading"
        title="AutoML Studio"
      />
      <div className="mt-6 grid gap-3 rounded-lg border border-border bg-card p-4 sm:grid-cols-2 xl:grid-cols-5">
        <Filter
          label="Status"
          onChange={(value) => {
            resetPage();
            setStatus(value as AutoMLStudyStatus | "");
          }}
          value={status}
        >
          <option value="">All statuses</option>
          {statuses.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </Filter>
        <Filter
          label="Task"
          onChange={(value) => {
            resetPage();
            setTask(value as AutoMLTask | "");
          }}
          value={task}
        >
          <option value="">All tasks</option>
          <option value="classification">Classification</option>
          <option value="regression">Regression</option>
        </Filter>
        <label className="text-sm font-medium text-foreground">
          Plugin
          <input
            className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
            onChange={(event) => {
              resetPage();
              setPlugin(event.target.value);
            }}
            value={plugin}
          />
        </label>
        {role === "admin" ? (
          <label className="text-sm font-medium text-foreground">
            Requester ID
            <input
              className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
              onChange={(event) => {
                resetPage();
                setRequester(event.target.value);
              }}
              value={requester}
            />
          </label>
        ) : null}
        <button
          className="self-end rounded-md border border-border-strong bg-elevated px-3 py-2 text-sm font-semibold"
          onClick={() => {
            setLoading(true);
            setRevision((value) => value + 1);
          }}
          type="button"
        >
          Refresh
        </button>
      </div>
      <div className="mt-5">
        {loading && page === null ? (
          <LoadingSkeleton label="Loading AutoML studies" />
        ) : error !== null ? (
          <InlineError
            message={error}
            onRetry={() => setRevision((value) => value + 1)}
          />
        ) : page === null || page.total === 0 ? (
          <EmptyState
            action={
              <Link className={primaryButtonClassName} to="/automl/new">
                Create study
              </Link>
            }
            description="No authorized AutoML studies match the selected filters."
            title="No AutoML studies"
          />
        ) : (
          <>
            <div className="overflow-x-auto rounded-lg border border-border bg-card">
              <table className="min-w-full divide-y divide-border text-left text-sm">
                <thead className="bg-muted text-xs uppercase text-secondary-foreground">
                  <tr>
                    <th className="px-4 py-3">Study</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Task / metric</th>
                    <th className="px-4 py-3">Trial progress</th>
                    <th className="px-4 py-3">Champion</th>
                    <th className="px-4 py-3">Created</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {page.items.map((study) => {
                    const progress = counts[study.study_id] ?? {};
                    const detail = details[study.study_id];
                    return (
                      <tr key={study.study_id}>
                        <td className="px-4 py-3">
                          <Link
                            className="font-mono text-xs font-semibold text-purple-700 hover:underline"
                            to={`/automl/studies/${study.study_id}`}
                          >
                            {study.study_id}
                          </Link>
                          <span className="mt-1 block text-xs text-muted-foreground">
                            {study.plugin_ids.join(", ")}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <AutoMLStatusBadge status={study.status} />
                        </td>
                        <td className="px-4 py-3 capitalize">
                          {study.task_type}
                          <span className="block text-xs text-muted-foreground">
                            {study.primary_metric} · {study.metric_direction}
                          </span>
                        </td>
                        <td
                          className="whitespace-nowrap px-4 py-3 text-xs"
                          aria-label={`Trial progress for study ${study.study_id}`}
                        >
                          ✓ {progress.succeeded ?? 0} · ⟳ {progress.running ?? 0} · ○{" "}
                          {progress.queued ?? 0} · ✕ {progress.failed ?? 0} · −{" "}
                          {(progress.cancelled ?? 0) + (progress.pruned ?? 0)}
                          <span className="block text-muted-foreground">
                            of {study.trial_budget} budgeted
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs">
                          {detail?.best_trial_id === null || detail === undefined
                            ? "Pending"
                            : "Best trial selected"}
                          <span className="block text-muted-foreground">
                            {detail?.register_champion
                              ? detail.champion_training_job_id === null
                                ? "Training handoff pending"
                                : "Training job linked"
                              : "Registration not requested"}
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3">
                          {formatDate(study.created_at)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <PaginationControls
              limit={page.limit}
              offset={page.offset}
              onPageChange={(value) => {
                setLoading(true);
                setOffset(value);
              }}
              total={page.total}
            />
          </>
        )}
      </div>
    </section>
  );
}

function Filter({
  children,
  label,
  onChange,
  value,
}: {
  readonly children: ReactNode;
  readonly label: string;
  readonly onChange: (value: string) => void;
  readonly value: string;
}): ReactElement {
  return (
    <label className="text-sm font-medium text-foreground">
      {label}
      <select
        className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2 capitalize"
        onChange={(event) => onChange(event.target.value)}
        value={value}
      >
        {children}
      </select>
    </label>
  );
}
