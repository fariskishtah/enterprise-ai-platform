import { useEffect, useState, type ReactElement, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getDataQuality,
  getDrift,
  getEvaluationHistory,
  getLatestEvaluation,
  getOperations,
  getPerformance,
  getReferenceProfile,
  triggerEvaluation,
  type DataQualitySummary,
  type DriftReport,
  type EvaluationPage,
  type MonitoringEvaluation,
  type OperationsSummary,
  type PerformanceSummary,
  type ReferenceProfile,
} from "../../api/monitoring";
import { getModelVersion } from "../../api/aiLifecycle";
import { isRequestCancelled } from "../../api/client";
import { useAuth } from "../../auth/useAuth";
import {
  InlineError,
  InlineNotice,
  LoadingSkeleton,
  primaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import {
  IntelligenceStatus,
  KeyValues,
  MetricGrid,
  formatDate,
  inputClassName,
  panelClassName,
} from "../../components/intelligence/IntelligenceUi";
import { PageHeader } from "../../components/ui/PageHeader";
type Reports = {
  operations?: OperationsSummary;
  quality?: DataQualitySummary;
  drift?: DriftReport;
  profile?: ReferenceProfile;
  evaluations?: EvaluationPage;
  latest?: MonitoringEvaluation;
  performance?: PerformanceSummary;
};
function Section({
  title,
  children,
}: {
  readonly title: string;
  readonly children: ReactNode;
}): ReactElement {
  return (
    <section className={panelClassName}>
      <h2 className="text-lg font-semibold text-foreground">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}
export function ModelMonitoringPage(): ReactElement {
  const { registeredModelName = "", versionOrAlias = "" } = useParams();
  const { role } = useAuth();
  const canEvaluate = role === "admin" || role === "engineer";
  const [data, setData] = useState<Reports | null>(null);
  const [resolvedVersion, setResolvedVersion] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [revision, setRevision] = useState(0);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    const c = new AbortController();
    let active = true;
    getModelVersion(registeredModelName, versionOrAlias, c.signal)
      .then((resolved) => {
        if (active) setResolvedVersion(resolved.model_version);
        const exactVersion = resolved.model_version;
        const calls = [
          getOperations(registeredModelName, exactVersion, c.signal),
          getDataQuality(registeredModelName, exactVersion, c.signal),
          getDrift(registeredModelName, exactVersion, c.signal),
          getReferenceProfile(registeredModelName, exactVersion, c.signal),
          getEvaluationHistory(registeredModelName, exactVersion, c.signal),
          getLatestEvaluation(registeredModelName, exactVersion, c.signal),
          getPerformance(registeredModelName, exactVersion, c.signal),
        ] as const;
        return Promise.allSettled(calls);
      })
      .then((r) => {
        if (!active) return;
        const names = [
          "operations",
          "quality",
          "drift",
          "profile",
          "evaluations",
          "latest",
          "performance",
        ] as const;
        const next: Reports = {};
        const failures: string[] = [];
        r.forEach((item, i) => {
          if (item.status === "fulfilled")
            Object.assign(next, { [names[i]]: item.value });
          else if (!isRequestCancelled(item.reason, c.signal))
            failures.push(
              `${names[i]}: ${item.reason instanceof Error ? item.reason.message : "Unavailable"}`,
            );
        });
        setData(next);
        setErrors(failures);
      })
      .catch((caught: unknown) => {
        if (!active || isRequestCancelled(caught, c.signal)) return;
        setErrors([
          caught instanceof Error
            ? caught.message
            : "Model version could not be resolved.",
        ]);
        setData({});
      });
    return () => {
      active = false;
      c.abort();
    };
  }, [registeredModelName, revision, versionOrAlias]);
  if (!data) return <LoadingSkeleton />;
  return (
    <section>
      <PageHeader
        eyebrow="Exact-version monitoring"
        headingId="model-monitoring-heading"
        title={`${registeredModelName} · ${versionOrAlias}`}
        description="Independent operational, quality, drift, reference, evaluation, and mature-outcome reports for this exact model context."
        actions={
          data.latest ? (
            <IntelligenceStatus value={data.latest.overall_status} />
          ) : undefined
        }
      />
      {errors.length ? (
        <div className="mt-5">
          <InlineNotice>
            Some sections are unavailable: {errors.join(" · ")}
          </InlineNotice>
        </div>
      ) : null}
      {canEvaluate ? (
        <form
          className={`${panelClassName} mt-6 grid gap-4 md:grid-cols-[1fr_1fr_auto]`}
          onSubmit={(e) => {
            e.preventDefault();
            void triggerEvaluation(
              registeredModelName,
              resolvedVersion ?? versionOrAlias,
              {
                window_start: from ? new Date(from).toISOString() : null,
                window_end: to ? new Date(to).toISOString() : null,
              },
            )
              .then(() => {
                setMessage("Monitoring evaluation completed.");
                setRevision((v) => v + 1);
              })
              .catch((caught: unknown) =>
                setMessage(
                  caught instanceof Error ? caught.message : "Evaluation failed.",
                ),
              );
          }}
        >
          <label className="text-sm">
            Window start (optional)
            <input
              type="datetime-local"
              className={inputClassName}
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </label>
          <label className="text-sm">
            Window end (optional)
            <input
              type="datetime-local"
              className={inputClassName}
              value={to}
              onChange={(e) => setTo(e.target.value)}
            />
          </label>
          <button className={`${primaryButtonClassName} self-end`} type="submit">
            Run evaluation
          </button>
          {message ? (
            <div className="md:col-span-3">
              <InlineNotice>{message}</InlineNotice>
            </div>
          ) : null}
        </form>
      ) : null}
      <div className="mt-6 grid gap-6">
        {data.operations ? (
          <Section title="Operations">
            <MetricGrid
              items={[
                { label: "Requests", value: data.operations.request_count },
                {
                  label: "Success rate",
                  value: `${(data.operations.success_rate * 100).toFixed(1)}%`,
                },
                {
                  label: "P95 latency",
                  value:
                    data.operations.p95_latency_ms === null
                      ? "Unavailable"
                      : `${data.operations.p95_latency_ms.toFixed(1)} ms`,
                },
                {
                  label: "Predicted rows",
                  value: data.operations.total_predicted_rows,
                },
              ]}
            />
            {data.operations.analysis_warning ? (
              <p className="mt-3 text-sm text-amber-900">
                {data.operations.analysis_warning}
              </p>
            ) : null}
          </Section>
        ) : (
          <InlineError
            message="Operational metrics are unavailable."
            onRetry={() => setRevision((v) => v + 1)}
          />
        )}
        {data.quality ? (
          <Section title="Request data quality">
            <MetricGrid
              items={[
                { label: "Requests", value: data.quality.request_count },
                { label: "Missing values", value: data.quality.missing_value_count },
                {
                  label: "Non-finite values",
                  value: data.quality.non_finite_value_count,
                },
                {
                  label: "Out of range",
                  value: data.quality.out_of_reference_range_count,
                },
              ]}
            />
            {data.quality.issues.length ? (
              <ul className="mt-4 space-y-2">
                {data.quality.issues.map((i) => (
                  <li
                    className="flex justify-between rounded-md bg-elevated p-3 text-sm"
                    key={i.code}
                  >
                    <span>{i.code}</span>
                    <IntelligenceStatus value={i.severity} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm text-muted-foreground">
                No aggregated quality issues were returned.
              </p>
            )}
          </Section>
        ) : (
          <InlineError
            message="Data-quality report is unavailable."
            onRetry={() => setRevision((v) => v + 1)}
          />
        )}
        {data.drift ? (
          <Section title="Drift">
            <div className="flex items-center gap-3">
              <IntelligenceStatus value={data.drift.aggregate_status} />
              <span className="text-sm text-secondary-foreground">
                {data.drift.current_sample_count} current /{" "}
                {data.drift.reference_sample_count} reference samples
              </span>
            </div>
            {data.drift.feature_results.length ? (
              <div className="mt-4 overflow-x-auto">
                <table className="min-w-full text-left text-sm">
                  <thead>
                    <tr>
                      <th className="px-3 py-2">Feature</th>
                      <th className="px-3 py-2">PSI</th>
                      <th className="px-3 py-2">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.drift.feature_results.map((f) => (
                      <tr className="border-t border-border" key={f.feature_index}>
                        <td className="px-3 py-2">{f.feature_index}</td>
                        <td className="px-3 py-2">{f.psi ?? "Insufficient data"}</td>
                        <td className="px-3 py-2">
                          <IntelligenceStatus value={f.severity} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="mt-3 text-sm text-muted-foreground">
                Not enough data for feature drift.
              </p>
            )}
          </Section>
        ) : (
          <InlineError
            message="Drift report is unavailable."
            onRetry={() => setRevision((v) => v + 1)}
          />
        )}
        {data.profile ? (
          <Section title="Evaluation reference profile">
            <KeyValues
              items={[
                { label: "Source", value: data.profile.source },
                { label: "Feature count", value: data.profile.feature_count },
                { label: "Sample count", value: data.profile.sample_count },
                { label: "Created", value: formatDate(data.profile.created_at) },
              ]}
            />
          </Section>
        ) : (
          <InlineError
            message="Reference profile is unavailable."
            onRetry={() => setRevision((v) => v + 1)}
          />
        )}
        {data.evaluations ? (
          <Section title="Evaluation history">
            {data.evaluations.items.length ? (
              <div className="space-y-2">
                {data.evaluations.items.map((e) => (
                  <Link
                    className="flex justify-between rounded-md bg-elevated p-3"
                    key={e.id}
                    to={`/monitoring/evaluations/${e.id}`}
                  >
                    <span>{formatDate(e.created_at)}</span>
                    <IntelligenceStatus value={e.overall_status} />
                  </Link>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No evaluations exist for this version.
              </p>
            )}
          </Section>
        ) : null}
        {data.performance ? (
          <Section title="Mature-outcome performance">
            <MetricGrid
              items={Object.entries(data.performance)
                .filter(
                  ([k, v]) =>
                    !["registered_model_name", "model_version", "task_type"].includes(
                      k,
                    ) && typeof v === "number",
                )
                .map(([label, value]) => ({
                  label: label.replaceAll("_", " "),
                  value: String(value),
                }))}
            />
          </Section>
        ) : (
          <Section title="Mature-outcome performance">
            <p className="text-sm text-muted-foreground">
              No mature-outcome performance summary is available.
            </p>
          </Section>
        )}
      </div>
    </section>
  );
}
