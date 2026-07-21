import { useEffect, useState, type ReactElement } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getRetrainingComparison,
  getRetrainingRequest,
  type CandidateComparison,
  type RetrainingRequest,
} from "../../api/retraining";
import {
  InlineError,
  InlineNotice,
  LoadingSkeleton,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import {
  IntelligenceStatus,
  KeyValues,
  formatDate,
  panelClassName,
} from "../../components/intelligence/IntelligenceUi";
import { PageHeader } from "../../components/ui/PageHeader";
import { useAuth } from "../../auth/useAuth";
import { isRequestCancelled } from "../../api/client";
const terminal = new Set(["completed", "failed", "cancelled"]);
export function RetrainingRequestPage(): ReactElement {
  const { role } = useAuth();
  const { id = "" } = useParams<{ id: string }>();
  const [item, setItem] = useState<RetrainingRequest | null>(null);
  const [comparison, setComparison] = useState<CandidateComparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (role === "operator") return;
    const c = new AbortController();
    let active = true;
    let timer: number | undefined;
    const load = () =>
      getRetrainingRequest(id, c.signal)
        .then((r) => {
          if (!active) return;
          setItem(r);
          setError(null);
          if (r.comparison) setComparison(r.comparison);
          else if (
            r.request_status === "candidate_created" ||
            r.request_status === "completed"
          )
            void getRetrainingComparison(id, c.signal)
              .then((value) => {
                if (active) setComparison(value);
              })
              .catch((caught: unknown) => {
                if (!isRequestCancelled(caught, c.signal)) return undefined;
              });
          if (!terminal.has(r.request_status)) timer = window.setTimeout(load, 5000);
        })
        .catch((e: unknown) => {
          if (!active || isRequestCancelled(e, c.signal)) return;
          setError(e instanceof Error ? e.message : "Request unavailable.");
          timer = window.setTimeout(load, 5000);
        });
    void load();
    return () => {
      active = false;
      c.abort();
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [id, revision, role]);
  if (role === "operator")
    return (
      <InlineError
        message="Retraining request detail is restricted to administrators and engineers."
        onRetry={() => history.back()}
      />
    );
  if (!item && error)
    return (
      <InlineError
        message={error}
        onRetry={() => {
          setError(null);
          setRevision((v) => v + 1);
        }}
      />
    );
  if (!item) return <LoadingSkeleton />;
  return (
    <section>
      <PageHeader
        eyebrow="Retraining request"
        headingId="request-heading"
        title={item.id}
        description={`${item.registered_model_name} · source version ${item.source_model_version}`}
        actions={<IntelligenceStatus value={item.request_status} />}
      />
      {!terminal.has(item.request_status) ? (
        <div className="mt-5">
          <InlineNotice>
            This nonterminal request refreshes every five seconds. No percentage
            progress is inferred.
          </InlineNotice>
        </div>
      ) : null}
      {error ? (
        <div className="mt-5">
          <InlineNotice>
            Latest refresh failed; showing the last confirmed state. {error}
          </InlineNotice>
        </div>
      ) : null}
      <div className="mt-6">
        <KeyValues
          items={[
            { label: "Trigger", value: item.trigger_type },
            { label: "Decision", value: item.decision_status },
            { label: "Mode", value: item.evaluation_mode },
            { label: "Requested", value: formatDate(item.requested_at) },
            { label: "Started", value: formatDate(item.started_at) },
            { label: "Completed", value: formatDate(item.completed_at) },
            {
              label: "Training job",
              value: item.training_job_id ? (
                <Link className="text-link" to={`/training/${item.training_job_id}`}>
                  {item.training_job_id}
                </Link>
              ) : (
                "Not submitted"
              ),
            },
            {
              label: "Resulting version",
              value: item.resulting_model_version ?? "Not created",
            },
            { label: "Failure", value: item.safe_failure_message ?? "None" },
          ]}
        />
      </div>
      <button
        className={`${secondaryButtonClassName} mt-5`}
        type="button"
        onClick={() => setRevision((v) => v + 1)}
      >
        Refresh now
      </button>
      {comparison ? (
        <section className={`${panelClassName} mt-6`}>
          <div className="flex justify-between">
            <h2 className="text-lg font-semibold">Candidate comparison</h2>
            <IntelligenceStatus value={comparison.status} />
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            Advisory source {comparison.source_model_version} versus candidate{" "}
            {comparison.candidate_model_version}. No winner or promotion is implied.
          </p>
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead>
                <tr>
                  <th className="px-3 py-2">Metric</th>
                  <th className="px-3 py-2">Source</th>
                  <th className="px-3 py-2">Candidate</th>
                  <th className="px-3 py-2">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {comparison.metrics.map((m) => (
                  <tr className="border-t border-border" key={m.metric}>
                    <td className="px-3 py-2">{m.metric}</td>
                    <td className="px-3 py-2">{m.source_value}</td>
                    <td className="px-3 py-2">{m.candidate_value}</td>
                    <td className="px-3 py-2">
                      <IntelligenceStatus value={m.outcome} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </section>
  );
}
