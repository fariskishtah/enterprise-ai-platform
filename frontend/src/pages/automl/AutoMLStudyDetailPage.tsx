import { useEffect, useState, type ReactElement } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import { getTrainingJob, type TrainingJob } from "../../api/aiLifecycle";
import {
  cancelAutoMLStudy,
  getAutoMLLeaderboard,
  getAutoMLStudy,
  listAutoMLTrials,
  type AutoMLLeaderboardEntry,
  type AutoMLStudyDetail,
  type AutoMLTrialPage,
  type AutoMLTrialStatus,
} from "../../api/automl";
import { isRequestCancelled } from "../../api/client";
import {
  AutoMLCard,
  AutoMLStatusBadge,
  KeyValues,
  compactParameters,
  formatMetric,
  terminalStudyStatuses,
} from "../../components/automl/AutoMLUi";
import { JobStatusBadge } from "../../components/aiLifecycle/LifecycleUi";
import { Dialog } from "../../components/hierarchy/Dialogs";
import {
  Breadcrumbs,
  InlineError,
  InlineNotice,
  LoadingSkeleton,
  PaginationControls,
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { PageHeader } from "../../components/ui/PageHeader";
import { formatDate, hierarchyError } from "../hierarchy/shared";

const PAGE_SIZE = 20;
const POLL_INTERVAL_MS = 3_000;
type Tab =
  "overview" | "leaderboard" | "trials" | "search" | "configuration" | "champion";

export function AutoMLStudyDetailPage(): ReactElement {
  const { studyId = "" } = useParams();
  const location = useLocation();
  const [study, setStudy] = useState<AutoMLStudyDetail | null>(null);
  const [trials, setTrials] = useState<AutoMLTrialPage | null>(null);
  const [leaderboard, setLeaderboard] = useState<readonly AutoMLLeaderboardEntry[]>([]);
  const [trainingJob, setTrainingJob] = useState<TrainingJob | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [trialStatus, setTrialStatus] = useState<AutoMLTrialStatus | "">("");
  const [trialPlugin, setTrialPlugin] = useState("");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async (): Promise<void> => {
      try {
        const [nextStudy, nextTrials, nextLeaderboard] = await Promise.all([
          getAutoMLStudy(studyId, controller.signal),
          listAutoMLTrials({
            limit: PAGE_SIZE,
            offset,
            pluginId: trialPlugin || undefined,
            signal: controller.signal,
            status: trialStatus || undefined,
            studyId,
          }),
          getAutoMLLeaderboard(studyId, controller.signal),
        ]);
        if (controller.signal.aborted) return;
        setStudy(nextStudy);
        setTrials(nextTrials);
        setLeaderboard(nextLeaderboard);
        setError(null);
        setLoading(false);
        if (nextStudy.champion_training_job_id !== null) {
          try {
            setTrainingJob(
              await getTrainingJob(
                nextStudy.champion_training_job_id,
                controller.signal,
              ),
            );
          } catch (caught) {
            if (!isRequestCancelled(caught, controller.signal)) setTrainingJob(null);
          }
        }
        if (!terminalStudyStatuses.has(nextStudy.status))
          timer = window.setTimeout(() => void load(), POLL_INTERVAL_MS);
      } catch (caught) {
        if (!isRequestCancelled(caught, controller.signal)) {
          setError(hierarchyError(caught));
          setLoading(false);
        }
      }
    };
    void load();
    return () => {
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [offset, revision, studyId, trialPlugin, trialStatus]);

  const cancel = async (): Promise<void> => {
    setCancelling(true);
    setCancelError(null);
    try {
      await cancelAutoMLStudy(studyId);
      setCancelOpen(false);
      setLoading(true);
      setRevision((value) => value + 1);
    } catch (caught) {
      setCancelError(hierarchyError(caught));
    } finally {
      setCancelling(false);
    }
  };
  if (loading && study === null)
    return <LoadingSkeleton label="Loading AutoML study" />;
  if (error !== null && study === null)
    return (
      <InlineError message={error} onRetry={() => setRevision((value) => value + 1)} />
    );
  if (study === null)
    return (
      <InlineError
        message="The requested AutoML study was not found."
        onRetry={() => setRevision((value) => value + 1)}
      />
    );
  const counts = countTrials(trials?.items ?? []);
  const best = leaderboard[0] ?? null;
  const canCancel =
    !terminalStudyStatuses.has(study.status) && study.cancel_requested_at === null;
  return (
    <section aria-labelledby="automl-study-heading">
      <Breadcrumbs
        items={[{ label: "AutoML Studio", to: "/automl" }, { label: study.study_id }]}
      />
      {typeof location.state === "object" &&
      location.state !== null &&
      "notice" in location.state ? (
        <div className="mb-4">
          <InlineNotice>{String(location.state.notice)}</InlineNotice>
        </div>
      ) : null}
      <PageHeader
        actions={
          canCancel ? (
            <button
              className={secondaryButtonClassName}
              onClick={() => setCancelOpen(true)}
              type="button"
            >
              Cancel study
            </button>
          ) : undefined
        }
        description={`${study.task_type} · ${study.primary_metric} (${study.metric_direction})`}
        eyebrow="AutoML study"
        headingId="automl-study-heading"
        title={study.study_id}
      />
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <AutoMLStatusBadge status={study.status} />
        {study.cancel_requested_at !== null ? (
          <span className="text-sm font-medium text-orange-700">
            Cancellation requested; active work is stopping.
          </span>
        ) : null}
      </div>
      <div
        aria-label="Study sections"
        className="mt-6 flex overflow-x-auto border-b border-border"
        role="tablist"
      >
        {(
          [
            "overview",
            "leaderboard",
            "trials",
            "search",
            "configuration",
            "champion",
          ] as const
        ).map((value) => (
          <button
            aria-controls={`panel-${value}`}
            aria-selected={tab === value}
            className={`whitespace-nowrap border-b-2 px-4 py-3 text-sm font-semibold capitalize ${tab === value ? "border-purple-600 text-purple-700" : "border-transparent text-muted-foreground"}`}
            id={`tab-${value}`}
            key={value}
            onClick={() => setTab(value)}
            role="tab"
            type="button"
          >
            {value === "search" ? "Search space" : value}
          </button>
        ))}
      </div>
      <div
        aria-labelledby={`tab-${tab}`}
        className="mt-5"
        id={`panel-${tab}`}
        role="tabpanel"
      >
        {tab === "overview" ? (
          <div className="space-y-5">
            <AutoMLCard>
              <KeyValues
                values={[
                  {
                    label: "Status",
                    value: <AutoMLStatusBadge status={study.status} />,
                  },
                  { label: "Created", value: formatDate(study.created_at) },
                  {
                    label: "Started",
                    value:
                      study.started_at === null
                        ? "Not started"
                        : formatDate(study.started_at),
                  },
                  {
                    label: "Finished",
                    value:
                      study.finished_at === null
                        ? "Not finished"
                        : formatDate(study.finished_at),
                  },
                  {
                    label: "Trial progress on this page",
                    value: `${counts.succeeded ?? 0} succeeded · ${counts.running ?? 0} running · ${counts.queued ?? 0} queued · ${counts.failed ?? 0} failed`,
                  },
                  {
                    label: "Budget",
                    value: `${study.trial_budget} trials · ${study.time_budget_seconds}s`,
                  },
                  {
                    label: "Best metric",
                    value: formatMetric(best?.primary_metric_value ?? null),
                  },
                  { label: "Best trial", value: study.best_trial_id ?? "Pending" },
                ]}
              />
            </AutoMLCard>
            {study.safe_error_message === null ? null : (
              <div
                className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800"
                role="alert"
              >
                {study.safe_error_message}
              </div>
            )}
            <InlineNotice>
              Progress is derived from currently loaded trial counts and the configured
              trial budget; it is not an estimated completion percentage.
            </InlineNotice>
          </div>
        ) : null}
        {tab === "leaderboard" ? (
          <Leaderboard studyId={study.study_id} values={leaderboard} />
        ) : null}
        {tab === "trials" ? (
          <Trials
            page={trials}
            plugin={trialPlugin}
            setOffset={setOffset}
            setPlugin={setTrialPlugin}
            setStatus={setTrialStatus}
            status={trialStatus}
            studyId={study.study_id}
          />
        ) : null}
        {tab === "search" ? (
          <AutoMLCard>
            <h2 className="mb-4 text-lg font-semibold">Persisted search spaces</h2>
            <SafeRecord
              value={{ plugins: study.plugin_ids, spaces: study.search_spaces }}
            />
          </AutoMLCard>
        ) : null}
        {tab === "configuration" ? (
          <AutoMLCard>
            <KeyValues
              values={[
                { label: "Sampler", value: study.sampler_type },
                { label: "Random seed", value: study.random_seed },
                { label: "CV folds", value: study.cross_validation_folds },
                {
                  label: "Per-trial timeout",
                  value: `${study.per_trial_timeout_seconds}s`,
                },
                { label: "Max study concurrency", value: study.max_concurrent_trials },
                {
                  label: "Preprocessing",
                  value: Object.entries(study.preprocessing)
                    .map(([key, value]) => `${key}: ${String(value)}`)
                    .join(", "),
                },
                {
                  label: "Training rows",
                  value: String(
                    study.data_specification.training_row_count ?? "Not available",
                  ),
                },
                {
                  label: "Evaluation rows",
                  value: String(
                    study.data_specification.evaluation_row_count ?? "Not available",
                  ),
                },
              ]}
            />
          </AutoMLCard>
        ) : null}
        {tab === "champion" ? (
          <Champion best={best} study={study} trainingJob={trainingJob} />
        ) : null}
      </div>
      {cancelOpen ? (
        <Dialog
          description="Queued trials cancel immediately. Active work may take a short time to terminate, and the page will continue polling until terminal."
          onClose={() => {
            if (!cancelling) setCancelOpen(false);
          }}
          title="Cancel AutoML study?"
        >
          <p className="text-sm text-muted-foreground">
            Cancellation is cooperative around folds and uses hard process termination
            for an active fit when necessary.
          </p>
          {cancelError === null ? null : (
            <p className="mt-4 text-sm text-red-700" role="alert">
              {cancelError}
            </p>
          )}
          <div className="mt-6 flex justify-end gap-3">
            <button
              className={secondaryButtonClassName}
              disabled={cancelling}
              onClick={() => setCancelOpen(false)}
              type="button"
            >
              Keep running
            </button>
            <button
              className={primaryButtonClassName}
              disabled={cancelling}
              onClick={() => void cancel()}
              type="button"
            >
              {cancelling ? "Requesting…" : "Request cancellation"}
            </button>
          </div>
        </Dialog>
      ) : null}
    </section>
  );
}

function Leaderboard({
  studyId,
  values,
}: {
  readonly studyId: string;
  readonly values: readonly AutoMLLeaderboardEntry[];
}): ReactElement {
  if (values.length === 0)
    return (
      <AutoMLCard>
        <h2 className="text-lg font-semibold">Leaderboard</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          No successful trials are ranked yet. Failed and cancelled trials remain
          available in the Trials section.
        </p>
      </AutoMLCard>
    );
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="min-w-full divide-y divide-border text-left text-sm">
        <thead className="bg-muted text-xs uppercase">
          <tr>
            <th className="px-4 py-3">Rank</th>
            <th className="px-4 py-3">Trial</th>
            <th className="px-4 py-3">Algorithm</th>
            <th className="px-4 py-3">Metric</th>
            <th className="px-4 py-3">Std dev</th>
            <th className="px-4 py-3">Duration</th>
            <th className="px-4 py-3">Parameters</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {values.map((entry) => (
            <tr key={entry.trial_id}>
              <td className="px-4 py-3 font-semibold">#{entry.rank}</td>
              <td className="px-4 py-3">
                <Link
                  className="font-semibold text-purple-700 hover:underline"
                  to={`/automl/studies/${studyId}/trials/${entry.trial_id}`}
                >
                  Trial {entry.trial_number}
                </Link>
              </td>
              <td className="px-4 py-3">{entry.plugin_id}</td>
              <td className="px-4 py-3 font-mono">
                {formatMetric(entry.primary_metric_value)}
              </td>
              <td className="px-4 py-3 font-mono">
                {formatMetric(entry.metric_standard_deviation)}
              </td>
              <td className="px-4 py-3">
                {entry.duration_seconds === null
                  ? "—"
                  : `${entry.duration_seconds.toFixed(2)}s`}
              </td>
              <td className="max-w-xs break-words px-4 py-3 text-xs">
                {compactParameters(entry.parameters)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function Trials({
  page,
  plugin,
  setOffset,
  setPlugin,
  setStatus,
  status,
  studyId,
}: {
  readonly page: AutoMLTrialPage | null;
  readonly plugin: string;
  readonly setOffset: (value: number) => void;
  readonly setPlugin: (value: string) => void;
  readonly setStatus: (value: AutoMLTrialStatus | "") => void;
  readonly status: AutoMLTrialStatus | "";
  readonly studyId: string;
}): ReactElement {
  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-3">
        <select
          aria-label="Trial status"
          className="rounded-md border border-border-strong bg-elevated px-3 py-2"
          onChange={(event) => {
            setOffset(0);
            setStatus(event.target.value as AutoMLTrialStatus | "");
          }}
          value={status}
        >
          <option value="">All statuses</option>
          {["queued", "running", "succeeded", "failed", "pruned", "cancelled"].map(
            (value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ),
          )}
        </select>
        <input
          aria-label="Trial plugin"
          className="rounded-md border border-border-strong bg-elevated px-3 py-2"
          onChange={(event) => {
            setOffset(0);
            setPlugin(event.target.value);
          }}
          placeholder="Plugin filter"
          value={plugin}
        />
      </div>
      {page === null || page.items.length === 0 ? (
        <AutoMLCard>
          <p className="text-sm text-muted-foreground">
            No trials match these filters.
          </p>
        </AutoMLCard>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <table className="min-w-full divide-y divide-border text-left text-sm">
              <thead className="bg-muted text-xs uppercase">
                <tr>
                  <th className="px-4 py-3">Trial</th>
                  <th className="px-4 py-3">Plugin</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Metric</th>
                  <th className="px-4 py-3">Duration</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {page.items.map((trial) => (
                  <tr key={trial.trial_id}>
                    <td className="px-4 py-3">
                      <Link
                        className="font-semibold text-purple-700 hover:underline"
                        to={`/automl/studies/${studyId}/trials/${trial.trial_id}`}
                      >
                        Trial {trial.trial_number}
                      </Link>
                    </td>
                    <td className="px-4 py-3">{trial.plugin_id}</td>
                    <td className="px-4 py-3">
                      <AutoMLStatusBadge status={trial.status} />
                    </td>
                    <td className="px-4 py-3 font-mono">
                      {formatMetric(trial.primary_metric_value)}
                    </td>
                    <td className="px-4 py-3">
                      {trial.duration_seconds === null
                        ? "—"
                        : `${trial.duration_seconds.toFixed(2)}s`}
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
  );
}
function Champion({
  best,
  study,
  trainingJob,
}: {
  readonly best: AutoMLLeaderboardEntry | null;
  readonly study: AutoMLStudyDetail;
  readonly trainingJob: TrainingJob | null;
}): ReactElement {
  return (
    <div className="space-y-5">
      <AutoMLCard>
        <h2 className="text-lg font-semibold">Selected configuration</h2>
        {best === null ? (
          <p className="mt-2 text-sm text-muted-foreground">
            A best trial has not been selected.
          </p>
        ) : (
          <KeyValues
            values={[
              {
                label: "Trial",
                value: (
                  <Link
                    className="text-purple-700"
                    to={`/automl/studies/${study.study_id}/trials/${best.trial_id}`}
                  >
                    Trial {best.trial_number}
                  </Link>
                ),
              },
              { label: "Plugin", value: best.plugin_id },
              {
                label: "Primary metric",
                value: formatMetric(best.primary_metric_value),
              },
              {
                label: "Variation",
                value: formatMetric(best.metric_standard_deviation),
              },
              { label: "Parameters", value: compactParameters(best.parameters) },
            ]}
          />
        )}
      </AutoMLCard>
      <AutoMLCard>
        <h2 className="text-lg font-semibold">Ordinary training handoff</h2>
        {!study.register_champion ? (
          <p className="mt-2 text-sm text-muted-foreground">
            Champion registration was not requested. The study completes after
            best-trial selection.
          </p>
        ) : study.champion_training_job_id === null ? (
          <p className="mt-2 text-sm text-muted-foreground">
            The winning configuration is waiting to enter the ordinary training
            pipeline.
          </p>
        ) : (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Link
              className="font-semibold text-purple-700 hover:underline"
              to={`/training/${study.champion_training_job_id}`}
            >
              Training job {study.champion_training_job_id}
            </Link>
            {trainingJob === null ? (
              <span className="text-sm text-muted-foreground">
                Status is temporarily unavailable.
              </span>
            ) : (
              <JobStatusBadge status={trainingJob.status} />
            )}
          </div>
        )}
        <p className="mt-3 text-xs text-muted-foreground">
          AutoML does not directly assign a production champion alias.
        </p>
      </AutoMLCard>
    </div>
  );
}
function SafeRecord({
  value,
}: {
  readonly value: Readonly<Record<string, unknown>>;
}): ReactElement {
  return (
    <dl className="space-y-3">
      {Object.entries(value).map(([key, item]) => (
        <div className="rounded border border-border bg-secondary p-3" key={key}>
          <dt className="text-xs font-semibold uppercase text-muted-foreground">
            {key.replaceAll("_", " ")}
          </dt>
          <dd className="mt-1 break-words font-mono text-xs text-foreground">
            {safeString(item)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
function safeString(value: unknown): string {
  if (value === null || value === undefined) return "Not available";
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  )
    return String(value);
  if (Array.isArray(value)) return value.map(safeString).join(" · ");
  if (typeof value === "object")
    return Object.entries(value)
      .map(([key, item]) => `${key}: ${safeString(item)}`)
      .join("; ");
  return "Unsupported value";
}
function countTrials(
  values: AutoMLTrialPage["items"],
): Partial<Record<AutoMLTrialStatus, number>> {
  const result: Partial<Record<AutoMLTrialStatus, number>> = {};
  for (const trial of values) result[trial.status] = (result[trial.status] ?? 0) + 1;
  return result;
}
