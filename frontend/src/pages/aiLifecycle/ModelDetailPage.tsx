import { useEffect, useMemo, useState, type ReactElement } from "react";
import { Link, useParams } from "react-router-dom";

import {
  getModelAliases,
  listPromotions,
  listTrainingJobs,
  type ModelAliases,
  type PromotionAuditPage,
  type TrainingJob,
} from "../../api/aiLifecycle";
import { Notice } from "../../components/aiLifecycle/LifecycleUi";
import { useAuth } from "../../auth/useAuth";
import {
  Breadcrumbs,
  EmptyState,
  InlineError,
  LoadingSkeleton,
  PaginationControls,
} from "../../components/hierarchy/ResourceStates";
import { formatDate, hierarchyError } from "../hierarchy/shared";

const PAGE_SIZE = 20;
export function ModelDetailPage(): ReactElement {
  const { role } = useAuth();
  const { registeredModelName = "" } = useParams();
  const name = decodeURIComponent(registeredModelName);
  const [aliases, setAliases] = useState<ModelAliases | null>(null);
  const [promotions, setPromotions] = useState<PromotionAuditPage | null>(null);
  const [jobs, setJobs] = useState<readonly TrainingJob[]>([]);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getModelAliases(name, controller.signal),
      role === "operator"
        ? Promise.resolve(null)
        : listPromotions(name, { limit: PAGE_SIZE, offset, signal: controller.signal }),
      role === "operator"
        ? Promise.resolve(null)
        : listTrainingJobs({
            limit: 100,
            offset: 0,
            signal: controller.signal,
            status: "succeeded",
          }),
    ])
      .then(([aliasResult, promotionResult, jobPage]) => {
        setAliases(aliasResult);
        setPromotions(promotionResult);
        setJobs(
          jobPage?.items.filter(
            (job) =>
              job.registered_model_name === name &&
              job.registered_model_version !== null,
          ) ?? [],
        );
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(hierarchyError(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [name, offset, revision, role]);
  const versions = useMemo(() => {
    const values = new Set<string>();
    jobs.forEach((job) => {
      if (job.registered_model_version) values.add(job.registered_model_version);
    });
    aliases?.aliases.forEach((alias) => values.add(alias.version));
    promotions?.items.forEach((audit) => {
      values.add(audit.model_version);
      if (audit.previous_version) values.add(audit.previous_version);
    });
    return [...values].sort((a, b) => Number(b) - Number(a));
  }, [aliases, jobs, promotions]);
  const comparable = jobs.filter((job) => job.metrics !== null);
  const comparisonPartner = comparable.find(
    (job, index) =>
      index > 0 &&
      job.trainer_key.algorithm === comparable[0]?.trainer_key.algorithm &&
      job.trainer_key.task_type === comparable[0]?.trainer_key.task_type,
  );
  const comparison =
    comparable[0] !== undefined && comparisonPartner !== undefined
      ? ([comparable[0], comparisonPartner] as const)
      : null;
  return (
    <section aria-labelledby="model-heading">
      <Breadcrumbs items={[{ label: "Models", to: "/models" }, { label: name }]} />
      <div className="border-b border-neutral-200 pb-6">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-purple-700">
          Registered model
        </p>
        <h2 className="break-all text-2xl font-semibold" id="model-heading">
          {name}
        </h2>
        <p className="mt-2 text-sm text-neutral-600">
          Registered model aliases, discoverable versions, and governed promotion
          history.
        </p>
      </div>
      <div className="mt-5">
        <Notice>
          Version history is limited to versions discoverable from visible training
          jobs, aliases, and promotion history.
        </Notice>
      </div>
      {loading ? (
        <div className="mt-5">
          <LoadingSkeleton />
        </div>
      ) : error !== null ? (
        <div className="mt-5">
          <InlineError
            message={error}
            onRetry={() => {
              setLoading(true);
              setError(null);
              setRevision((value) => value + 1);
            }}
          />
        </div>
      ) : (
        <>
          <section className="mt-7">
            <h3 className="text-lg font-semibold">Aliases</h3>
            {aliases === null || aliases.aliases.length === 0 ? (
              <p className="mt-2 text-sm text-neutral-500">
                No governed aliases are assigned.
              </p>
            ) : (
              <div className="mt-3 flex flex-wrap gap-2">
                {aliases.aliases.map((alias) => (
                  <Link
                    className="rounded-full border border-purple-200 bg-purple-50 px-3 py-1 text-sm font-semibold text-purple-800"
                    key={alias.alias}
                    to={`/models/${encodeURIComponent(name)}/versions/${encodeURIComponent(alias.version)}`}
                  >
                    {alias.alias} · v{alias.version}
                  </Link>
                ))}
              </div>
            )}
          </section>
          <section className="mt-8">
            <h3 className="text-lg font-semibold">Discoverable versions</h3>
            {versions.length === 0 ? (
              <div className="mt-3">
                <EmptyState
                  description="No versions can be discovered from the authorized sources."
                  title="No discoverable versions"
                />
              </div>
            ) : (
              <ul className="mt-3 divide-y divide-neutral-100 rounded-lg border border-neutral-200 bg-white">
                {versions.map((version) => {
                  const linked = jobs.find(
                    (job) => job.registered_model_version === version,
                  );
                  return (
                    <li
                      className="flex flex-wrap items-center justify-between gap-3 p-4"
                      key={version}
                    >
                      <div>
                        <Link
                          className="font-semibold text-purple-700 hover:underline"
                          to={`/models/${encodeURIComponent(name)}/versions/${encodeURIComponent(version)}`}
                        >
                          Version {version}
                        </Link>
                        <p className="mt-1 text-xs text-neutral-500">
                          {linked
                            ? `Visible job ${linked.job_id}`
                            : "Discovered through governance state; metrics unavailable"}
                        </p>
                      </div>
                      {linked ? (
                        <span className="text-xs text-neutral-500">
                          {formatDate(linked.finished_at ?? linked.created_at)}
                        </span>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
          {comparison ? (
            <section className="mt-8">
              <h3 className="text-lg font-semibold">Limited metric comparison</h3>
              <p className="mt-1 text-sm text-neutral-500">
                Based only on the two newest visible completed training-job metrics. No
                winner is inferred.
              </p>
              <div className="mt-4 overflow-x-auto rounded-lg border border-neutral-200">
                <table className="min-w-full text-left text-sm">
                  <thead className="bg-neutral-50">
                    <tr>
                      <th className="px-4 py-3">Metric</th>
                      <th className="px-4 py-3">
                        v{comparison[0].registered_model_version}
                      </th>
                      <th className="px-4 py-3">
                        v{comparison[1].registered_model_version}
                      </th>
                      <th className="px-4 py-3">Difference</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.keys(comparison[0].metrics ?? {})
                      .filter((key) => typeof comparison[1].metrics?.[key] === "number")
                      .map((key) => {
                        const first = comparison[0].metrics?.[key] ?? 0;
                        const second = comparison[1].metrics?.[key] ?? 0;
                        return (
                          <tr className="border-t" key={key}>
                            <th className="px-4 py-3">{key.replaceAll("_", " ")}</th>
                            <td className="px-4 py-3">{first.toPrecision(6)}</td>
                            <td className="px-4 py-3">{second.toPrecision(6)}</td>
                            <td className="px-4 py-3">
                              {(first - second).toPrecision(6)}
                            </td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}
          <section className="mt-8">
            <h3 className="text-lg font-semibold">Promotion history</h3>
            {promotions === null || promotions.total === 0 ? (
              <p className="mt-2 text-sm text-neutral-500">
                {role === "operator"
                  ? "Promotion history is available only to admins and engineers."
                  : "No promotion attempts are recorded."}
              </p>
            ) : (
              <>
                <ul className="mt-3 space-y-3">
                  {promotions.items.map((audit) => (
                    <li
                      className="rounded-lg border border-neutral-200 bg-white p-4"
                      key={audit.audit_id}
                    >
                      <div className="flex flex-wrap justify-between gap-3">
                        <p className="font-semibold">
                          Version {audit.model_version} → {audit.target_alias}
                        </p>
                        <span className="text-sm capitalize text-neutral-600">
                          {audit.decision} · {audit.operation_outcome}
                        </span>
                      </div>
                      <p className="mt-2 text-xs text-neutral-500">
                        Requested {formatDate(audit.created_at)} by{" "}
                        {audit.requested_by_user_id}
                      </p>
                      {audit.safe_error_message ? (
                        <p className="mt-2 text-sm text-red-700">
                          {audit.safe_error_message}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
                <PaginationControls
                  limit={promotions.limit}
                  offset={promotions.offset}
                  onPageChange={setOffset}
                  total={promotions.total}
                />
              </>
            )}
          </section>
        </>
      )}
    </section>
  );
}
