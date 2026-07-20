import { useEffect, useState, type ReactElement } from "react";
import { useParams } from "react-router-dom";

import {
  getModelVersion,
  listTrainingJobs,
  promoteModel,
  type ModelVersion,
  type PromotionResult,
  type TrainingJob,
} from "../../api/aiLifecycle";
import { useAuth } from "../../auth/useAuth";
import { MetricsGrid, TrainerLabel } from "../../components/aiLifecycle/LifecycleUi";
import { Dialog } from "../../components/hierarchy/Dialogs";
import {
  Breadcrumbs,
  InlineError,
  LoadingSkeleton,
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { hierarchyError } from "../hierarchy/shared";

type PromotionTarget = "challenger" | "champion";
export function ModelVersionPage(): ReactElement {
  const { role } = useAuth();
  const { registeredModelName = "", versionOrAlias = "" } = useParams();
  const name = decodeURIComponent(registeredModelName);
  const reference = decodeURIComponent(versionOrAlias);
  const [version, setVersion] = useState<ModelVersion | null>(null);
  const [job, setJob] = useState<TrainingJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [target, setTarget] = useState<PromotionTarget | null>(null);
  const [force, setForce] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [result, setResult] = useState<PromotionResult | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getModelVersion(name, reference, controller.signal),
      role === "operator"
        ? Promise.resolve(null)
        : listTrainingJobs({
            limit: 100,
            offset: 0,
            signal: controller.signal,
            status: "succeeded",
          }),
    ])
      .then(([resolved, jobs]) => {
        setVersion(resolved);
        setJob(
          jobs?.items.find(
            (item) =>
              item.registered_model_name === name &&
              item.registered_model_version === resolved.model_version,
          ) ?? null,
        );
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(hierarchyError(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [name, reference, revision, role]);
  if (loading) return <LoadingSkeleton label="Loading model version" />;
  if (error !== null || version === null)
    return (
      <InlineError
        message={error ?? "Model version was not found."}
        onRetry={() => {
          setLoading(true);
          setError(null);
          setRevision((value) => value + 1);
        }}
      />
    );
  const canChallenger = role === "admin" || role === "engineer";
  const canChampion = role === "admin" && version.aliases.includes("challenger");
  return (
    <section aria-labelledby="version-heading">
      <Breadcrumbs
        items={[
          { label: "Models", to: "/models" },
          { label: name, to: `/models/${encodeURIComponent(name)}` },
          { label: `Version ${version.model_version}` },
        ]}
      />
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-neutral-200 pb-6">
        <div>
          <h2 className="text-2xl font-semibold" id="version-heading">
            Version {version.model_version}
          </h2>
          <p className="mt-2 break-all text-sm text-neutral-600">
            {version.model_name}
          </p>
        </div>
        <div className="flex gap-2">
          {canChallenger ? (
            <button
              className={secondaryButtonClassName}
              onClick={() => setTarget("challenger")}
              type="button"
            >
              Promote to challenger
            </button>
          ) : null}
          {canChampion ? (
            <button
              className={primaryButtonClassName}
              onClick={() => setTarget("champion")}
              type="button"
            >
              Promote to champion
            </button>
          ) : null}
        </div>
      </div>
      {result ? (
        <div
          className="mt-5 rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900"
          role="status"
        >
          <p className="font-semibold">Promotion completed: {result.target_alias}</p>
          <p className="mt-1">{result.policy_evaluation.reason}</p>
        </div>
      ) : null}
      <dl className="mt-6 grid gap-4 rounded-lg border border-neutral-200 bg-white p-5 sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <dt className="text-xs font-semibold uppercase text-neutral-500">
            Registry status
          </dt>
          <dd className="mt-1">{version.status}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-neutral-500">Trainer</dt>
          <dd className="mt-1 capitalize">
            <TrainerLabel trainer={version.trainer_key} />
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-neutral-500">Run ID</dt>
          <dd className="mt-1 break-all font-mono text-xs">{version.run_id}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-neutral-500">Aliases</dt>
          <dd className="mt-1">
            {version.aliases.length ? version.aliases.join(", ") : "None"}
          </dd>
        </div>
      </dl>
      <div className="mt-8">
        <h3 className="mb-4 text-lg font-semibold">Visible training-job metrics</h3>
        <MetricsGrid metrics={job?.metrics ?? null} />
        {job === null ? (
          <p className="mt-2 text-xs text-neutral-500">
            No authorized completed training job links this exact version.
          </p>
        ) : null}
      </div>
      {target ? (
        <Dialog
          description={`This requests assignment of the ${target} alias. It does not claim or perform production deployment.`}
          onClose={() => setTarget(null)}
          title={`Promote version ${version.model_version} to ${target}?`}
        >
          <div className="space-y-4">
            {role === "admin" ? (
              <label className="flex items-center gap-2 text-sm">
                <input
                  checked={force}
                  onChange={(event) => setForce(event.target.checked)}
                  type="checkbox"
                />
                Force a policy-rejected evaluation
              </label>
            ) : null}
            <div>
              <label className="block text-sm font-medium" htmlFor="promotion-reason">
                Reason (optional)
              </label>
              <textarea
                className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm"
                id="promotion-reason"
                onChange={(event) => setReason(event.target.value)}
                rows={3}
                value={reason}
              />
            </div>
            {mutationError ? (
              <p className="rounded-md bg-red-50 p-3 text-sm text-red-800" role="alert">
                {mutationError}
              </p>
            ) : null}
            <div className="flex justify-end gap-3">
              <button
                className={secondaryButtonClassName}
                disabled={busy}
                onClick={() => setTarget(null)}
                type="button"
              >
                Cancel
              </button>
              <button
                className={primaryButtonClassName}
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  setMutationError(null);
                  promoteModel(name, version.model_version, target, {
                    force: role === "admin" && force,
                    reason: reason.trim() || null,
                  })
                    .then((promotion) => {
                      setResult(promotion);
                      setTarget(null);
                      setRevision((value) => value + 1);
                    })
                    .catch((caught: unknown) =>
                      setMutationError(hierarchyError(caught)),
                    )
                    .finally(() => setBusy(false));
                }}
                type="button"
              >
                {busy ? "Promoting…" : `Confirm ${target} promotion`}
              </button>
            </div>
          </div>
        </Dialog>
      ) : null}
    </section>
  );
}
