import { useEffect, useState, type ReactElement } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  evaluateRetraining,
  getRetrainingStatus,
  listPolicies,
  listRetrainingAudits,
  listRetrainingRequests,
  requestRetraining,
  updatePolicy,
  type RetrainingAuditPage,
  type RetrainingEvaluation,
  type RetrainingPolicy,
  type RetrainingRequestPage,
  type RetrainingStatus,
  type RetrainingTrigger,
} from "../../api/retraining";
import { useAuth } from "../../auth/useAuth";
import {
  EmptyState,
  InlineError,
  InlineNotice,
  LoadingSkeleton,
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import {
  IntelligenceStatus,
  MetricGrid,
  formatDate,
  inputClassName,
  panelClassName,
} from "../../components/intelligence/IntelligenceUi";
import { PageHeader } from "../../components/ui/PageHeader";
import { isRequestCancelled } from "../../api/client";
export function RetrainingPage(): ReactElement {
  const { role } = useAuth();
  const navigate = useNavigate();
  const canManage = role === "admin" || role === "engineer";
  const [status, setStatus] = useState<RetrainingStatus | null>(null);
  const [requests, setRequests] = useState<RetrainingRequestPage | null>(null);
  const [policies, setPolicies] = useState<readonly RetrainingPolicy[]>([]);
  const [audits, setAudits] = useState<RetrainingAuditPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const [version, setVersion] = useState("");
  const [reason, setReason] = useState("");
  const [trigger, setTrigger] = useState<RetrainingTrigger>("feature_drift");
  const [decision, setDecision] = useState<RetrainingEvaluation | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const c = new AbortController();
    let active = true;
    Promise.allSettled([
      getRetrainingStatus(c.signal),
      canManage
        ? listRetrainingRequests({ limit: 20, offset: 0, signal: c.signal })
        : Promise.resolve(null),
      canManage ? listPolicies(c.signal) : Promise.resolve([]),
      role === "admin"
        ? listRetrainingAudits({ limit: 50, offset: 0, signal: c.signal })
        : Promise.resolve(null),
    ]).then(([statusResult, requestsResult, policiesResult, auditsResult]) => {
      if (!active) return;
      if (statusResult.status === "fulfilled") setStatus(statusResult.value);
      else if (!isRequestCancelled(statusResult.reason, c.signal))
        setError(
          statusResult.reason instanceof Error
            ? statusResult.reason.message
            : "Retraining unavailable.",
        );
      if (requestsResult.status === "fulfilled") setRequests(requestsResult.value);
      if (policiesResult.status === "fulfilled") setPolicies(policiesResult.value);
      if (auditsResult.status === "fulfilled") setAudits(auditsResult.value);
      const optionalResults = [
        ["Requests", requestsResult],
        ["Policies", policiesResult],
        ["Audits", auditsResult],
      ] as const;
      setWarnings(
        optionalResults.flatMap(([label, result]) =>
          result.status === "rejected" && !isRequestCancelled(result.reason, c.signal)
            ? [
                `${label}: ${result.reason instanceof Error ? result.reason.message : "Unavailable."}`,
              ]
            : [],
        ),
      );
    });
    return () => {
      active = false;
      c.abort();
    };
  }, [canManage, revision, role]);
  if (error)
    return (
      <InlineError
        message={error}
        onRetry={() => {
          setError(null);
          setRevision((v) => v + 1);
        }}
      />
    );
  if (!status) return <LoadingSkeleton />;
  return (
    <section>
      <PageHeader
        eyebrow="Intelligence operations"
        headingId="retraining-heading"
        title="Controlled retraining"
        description="Policy-governed retraining decisions and durable request lifecycle. No cancellation, automatic deployment, rollback, or client-side promotion is available."
      />
      {warnings.length ? (
        <div className="mt-5">
          <InlineNotice>{warnings.join(" ")}</InlineNotice>
        </div>
      ) : null}
      <div className="mt-6">
        <MetricGrid
          items={[
            { label: "Total requests", value: status.total_requests },
            { label: "Active", value: status.active_requests },
            { label: "Completed", value: status.completed_requests },
            { label: "Failed", value: status.failed_requests },
          ]}
        />
      </div>
      {!canManage ? (
        <div className="mt-6">
          <InlineNotice>
            Operators have aggregate retraining visibility only. Policies, requests,
            evaluations, and mutations are restricted.
          </InlineNotice>
        </div>
      ) : (
        <>
          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <form
              className={panelClassName}
              onSubmit={(e) => {
                e.preventDefault();
                void evaluateRetraining(model, version, {
                  trigger_type: trigger,
                  start_at: null,
                  end_at: null,
                  minimum_sample_count: null,
                  submit_if_eligible: true,
                })
                  .then((r) => {
                    setDecision(r);
                    if (r.request) navigate(`/retraining/requests/${r.request.id}`);
                  })
                  .catch((caught: unknown) =>
                    setError(
                      caught instanceof Error ? caught.message : "Evaluation failed.",
                    ),
                  );
              }}
            >
              <h2 className="text-lg font-semibold">
                Automatic eligibility evaluation
              </h2>
              <div className="mt-4 grid gap-3">
                <label className="text-sm">
                  Model
                  <input
                    required
                    className={inputClassName}
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                  />
                </label>
                <label className="text-sm">
                  Version or alias
                  <input
                    required
                    className={inputClassName}
                    value={version}
                    onChange={(e) => setVersion(e.target.value)}
                  />
                </label>
                <label className="text-sm">
                  Trigger
                  <select
                    className={inputClassName}
                    value={trigger}
                    onChange={(e) => setTrigger(e.target.value as RetrainingTrigger)}
                  >
                    <option value="feature_drift">Feature drift</option>
                    <option value="prediction_drift">Prediction drift</option>
                    <option value="data_quality">Data quality</option>
                  </select>
                </label>
              </div>
              <button className={`${primaryButtonClassName} mt-4`} type="submit">
                Evaluate and submit if eligible
              </button>
            </form>
            <form
              className={panelClassName}
              onSubmit={(e) => {
                e.preventDefault();
                if (!confirm("Submit this manual retraining request?")) return;
                void requestRetraining(model, version, {
                  reason,
                  override_cooldown: false,
                })
                  .then((r) => {
                    setDecision(r);
                    if (r.request) navigate(`/retraining/requests/${r.request.id}`);
                  })
                  .catch((caught: unknown) =>
                    setError(
                      caught instanceof Error ? caught.message : "Request failed.",
                    ),
                  );
              }}
            >
              <h2 className="text-lg font-semibold">Manual retraining request</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                Uses the model and version entered alongside the eligibility form.
              </p>
              <label className="mt-4 block text-sm">
                Required reason
                <textarea
                  required
                  maxLength={1000}
                  className={`${inputClassName} min-h-28`}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
              <button className={`${secondaryButtonClassName} mt-4`} type="submit">
                Review and submit request
              </button>
            </form>
          </div>
          {decision ? (
            <div className={`${panelClassName} mt-6`}>
              <h2 className="text-lg font-semibold">Latest decision</h2>
              <div className="mt-3 flex items-center gap-3">
                <IntelligenceStatus value={decision.decision.decision_status} />
                <span className="text-sm text-secondary-foreground">
                  {decision.decision.reasons.join(" · ") || "No reason returned."}
                </span>
              </div>
            </div>
          ) : null}
          <div className="mt-6">
            <h2 className="text-lg font-semibold">Recent requests</h2>
            {requests?.items.length ? (
              <div className="mt-3 overflow-x-auto rounded-lg border border-border bg-card">
                <table className="min-w-full text-left text-sm">
                  <thead>
                    <tr>
                      <th className="px-4 py-3">Model/version</th>
                      <th className="px-4 py-3">Trigger</th>
                      <th className="px-4 py-3">Status</th>
                      <th className="px-4 py-3">Requested</th>
                      <th className="px-4 py-3">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {requests.items.map((r) => (
                      <tr className="border-t border-border" key={r.id}>
                        <td className="px-4 py-3">
                          {r.registered_model_name} / {r.source_model_version}
                        </td>
                        <td className="px-4 py-3">{r.trigger_type}</td>
                        <td className="px-4 py-3">
                          <IntelligenceStatus value={r.request_status} />
                        </td>
                        <td className="px-4 py-3">{formatDate(r.requested_at)}</td>
                        <td className="px-4 py-3">
                          <Link
                            className="font-semibold text-link"
                            to={`/retraining/requests/${r.id}`}
                          >
                            Open
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="mt-3">
                <EmptyState
                  title="No retraining requests"
                  description="No controlled retraining requests are visible."
                />
              </div>
            )}
          </div>
          <div className="mt-6">
            <h2 className="text-lg font-semibold">Policies</h2>
            <div className="mt-3 grid gap-4 lg:grid-cols-2">
              {policies.map((p) => (
                <article className={panelClassName} key={p.id}>
                  <div className="flex justify-between">
                    <h3 className="font-semibold">{p.registered_model_name}</h3>
                    <IntelligenceStatus value={p.enabled ? "healthy" : "disabled"} />
                  </div>
                  <p className="mt-2 text-sm text-secondary-foreground">
                    Minimum {p.minimum_current_sample_count} samples ·{" "}
                    {p.cooldown_seconds}s cooldown · {p.maximum_active_requests} active
                    maximum
                  </p>
                  {role === "admin" ? (
                    <button
                      className={`${secondaryButtonClassName} mt-3`}
                      type="button"
                      onClick={() => {
                        if (!confirm(`Toggle policy for ${p.registered_model_name}?`))
                          return;
                        void updatePolicy(p.registered_model_name, {
                          enabled: !p.enabled,
                          allowed_trigger_types: p.allowed_trigger_types,
                          minimum_drift_status: p.minimum_drift_status,
                          minimum_current_sample_count: p.minimum_current_sample_count,
                          cooldown_seconds: p.cooldown_seconds,
                          maximum_requests_per_day: p.maximum_requests_per_day,
                          maximum_requests_per_week: p.maximum_requests_per_week,
                          maximum_active_requests: p.maximum_active_requests,
                          require_champion_source: p.require_champion_source,
                          allow_truncated_drift: p.allow_truncated_drift,
                        })
                          .then(() => setRevision((v) => v + 1))
                          .catch((caught: unknown) =>
                            setError(
                              caught instanceof Error
                                ? caught.message
                                : "Policy update failed.",
                            ),
                          );
                      }}
                    >
                      Toggle enabled state
                    </button>
                  ) : null}
                </article>
              ))}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Policy listing is bounded and the backend does not expose a total count.
            </p>
          </div>
          {audits ? (
            <div className="mt-6">
              <h2 className="text-lg font-semibold">Admin audit history</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                {audits.total} append-only evaluation audit records; showing{" "}
                {audits.items.length}.
              </p>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
