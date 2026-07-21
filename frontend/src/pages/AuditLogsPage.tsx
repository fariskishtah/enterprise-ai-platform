import { useEffect, useState, type ReactElement } from "react";

import { listPromotions, type PromotionAuditPage } from "../api/aiLifecycle";
import { isRequestCancelled } from "../api/client";
import { listRetrainingAudits, type RetrainingAuditPage } from "../api/retraining";
import { useAuth } from "../auth/useAuth";
import {
  EmptyState,
  InlineNotice,
  LoadingSkeleton,
  PaginationControls,
  primaryButtonClassName,
} from "../components/hierarchy/ResourceStates";
import {
  IntelligenceStatus,
  formatDate,
  inputClassName,
  panelClassName,
} from "../components/intelligence/IntelligenceUi";
import { PageHeader } from "../components/ui/PageHeader";

const LIMIT = 20;

function SectionError({
  message,
  onRetry,
}: {
  readonly message: string;
  readonly onRetry: () => void;
}): ReactElement {
  return (
    <div className="rounded-lg border border-danger-200 bg-danger-50 p-4" role="alert">
      <h4 className="font-semibold text-danger-900">Audit source unavailable</h4>
      <p className="mt-1 text-sm text-danger-800">{message}</p>
      <button
        className="mt-3 rounded-md border border-danger-300 bg-card px-3 py-2 text-sm font-semibold text-danger-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger-700"
        onClick={onRetry}
        type="button"
      >
        Retry this source
      </button>
    </div>
  );
}

export function AuditLogsPage(): ReactElement {
  const { role } = useAuth();
  const [modelInput, setModelInput] = useState("");
  const [modelName, setModelName] = useState("");
  const [promotionOffset, setPromotionOffset] = useState(0);
  const [promotionPage, setPromotionPage] = useState<PromotionAuditPage | null>(null);
  const [promotionError, setPromotionError] = useState<string | null>(null);
  const [promotionRevision, setPromotionRevision] = useState(0);
  const [retrainingOffset, setRetrainingOffset] = useState(0);
  const [retrainingPage, setRetrainingPage] = useState<RetrainingAuditPage | null>(
    null,
  );
  const [retrainingError, setRetrainingError] = useState<string | null>(null);
  const [retrainingRevision, setRetrainingRevision] = useState(0);

  useEffect(() => {
    if (role !== "admin") return;
    const controller = new AbortController();
    let active = true;
    listRetrainingAudits({
      limit: LIMIT,
      offset: retrainingOffset,
      signal: controller.signal,
    })
      .then((page) => {
        if (active) {
          setRetrainingPage(page);
          setRetrainingError(null);
        }
      })
      .catch((error: unknown) => {
        if (active && !isRequestCancelled(error, controller.signal))
          setRetrainingError(
            error instanceof Error ? error.message : "Retraining audits unavailable.",
          );
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [retrainingOffset, retrainingRevision, role]);

  useEffect(() => {
    if (role === "operator" || !modelName) return;
    const controller = new AbortController();
    let active = true;
    listPromotions(modelName, {
      limit: LIMIT,
      offset: promotionOffset,
      signal: controller.signal,
    })
      .then((page) => {
        if (active) {
          setPromotionPage(page);
          setPromotionError(null);
        }
      })
      .catch((error: unknown) => {
        if (active && !isRequestCancelled(error, controller.signal))
          setPromotionError(
            error instanceof Error ? error.message : "Promotion audits unavailable.",
          );
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [modelName, promotionOffset, promotionRevision, role]);

  if (role === "operator")
    return (
      <section>
        <PageHeader
          eyebrow="Governance"
          headingId="audit-logs-heading"
          title="Audit Logs"
          description="Available audit sources are restricted to administrators and engineers."
        />
        <div className="mt-6">
          <EmptyState
            title="Restricted audit data"
            description="Your role does not have access to the backend audit sources exposed in this workspace."
          />
        </div>
      </section>
    );

  return (
    <section>
      <PageHeader
        eyebrow="Governance"
        headingId="audit-logs-heading"
        title="Audit Logs"
        description="Supported domain audit records only. This is not a complete platform-wide activity log."
      />
      <div className="mt-5">
        <InlineNotice>
          Coverage is limited to model promotion audits and, for administrators,
          retraining evaluation audits. Authentication and other operational audit
          events are retained in server logs and are not exposed by the current API.
        </InlineNotice>
      </div>

      <section className="mt-6" aria-labelledby="promotion-audits-heading">
        <div className={panelClassName}>
          <h3
            className="text-lg font-semibold text-foreground"
            id="promotion-audits-heading"
          >
            Model promotion audits
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            The backend requires an exact registered model name and supports pagination
            only.
          </p>
          <form
            className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end"
            onSubmit={(event) => {
              event.preventDefault();
              setPromotionOffset(0);
              setPromotionPage(null);
              setPromotionError(null);
              setModelName(modelInput.trim());
              setPromotionRevision((value) => value + 1);
            }}
          >
            <label className="min-w-0 flex-1 text-sm font-medium text-secondary-foreground">
              Registered model name
              <input
                className={inputClassName}
                onChange={(event) => setModelInput(event.target.value)}
                required
                value={modelInput}
              />
            </label>
            <button className={primaryButtonClassName} type="submit">
              Load promotion audits
            </button>
          </form>
        </div>
        {promotionError ? (
          <div className="mt-4">
            <SectionError
              message={promotionError}
              onRetry={() => {
                setPromotionError(null);
                setPromotionRevision((value) => value + 1);
              }}
            />
          </div>
        ) : modelName && promotionPage === null ? (
          <div className="mt-4">
            <LoadingSkeleton label="Loading promotion audits" />
          </div>
        ) : promotionPage?.items.length ? (
          <div className="mt-4 overflow-x-auto rounded-lg border border-border bg-card">
            <table className="min-w-[900px] w-full text-left text-sm">
              <thead className="bg-muted text-muted-foreground">
                <tr>
                  <th className="px-4 py-3">Timestamp</th>
                  <th className="px-4 py-3">Actor</th>
                  <th className="px-4 py-3">Action</th>
                  <th className="px-4 py-3">Resource</th>
                  <th className="px-4 py-3">Outcome</th>
                  <th className="px-4 py-3">Detail</th>
                </tr>
              </thead>
              <tbody>
                {promotionPage.items.map((item) => (
                  <tr className="border-t border-border" key={item.audit_id}>
                    <td className="px-4 py-3">{formatDate(item.created_at)}</td>
                    <td className="px-4 py-3 font-mono text-xs">
                      {item.requested_by_user_id}
                    </td>
                    <td className="px-4 py-3">{item.action.replaceAll("_", " ")}</td>
                    <td className="px-4 py-3">
                      {item.registered_model_name} / {item.model_version}
                    </td>
                    <td className="px-4 py-3">
                      <IntelligenceStatus value={item.operation_outcome} />
                    </td>
                    <td className="px-4 py-3">
                      <details>
                        <summary className="cursor-pointer font-semibold text-link">
                          Safe detail
                        </summary>
                        <div className="mt-2 max-w-sm text-xs text-secondary-foreground">
                          Target alias: {item.target_alias}. Decision: {item.decision}.{" "}
                          {item.safe_error_message ??
                            item.reason ??
                            "No additional detail."}
                        </div>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="px-4 pb-4">
              <PaginationControls
                limit={LIMIT}
                offset={promotionOffset}
                onPageChange={setPromotionOffset}
                total={promotionPage.total}
              />
            </div>
          </div>
        ) : modelName && promotionPage ? (
          <div className="mt-4">
            <EmptyState
              title="No promotion audits"
              description="No promotion attempts exist for this registered model."
            />
          </div>
        ) : null}
      </section>

      {role === "admin" ? (
        <section className="mt-8" aria-labelledby="retraining-audits-heading">
          <h3
            className="text-lg font-semibold text-foreground"
            id="retraining-audits-heading"
          >
            Retraining evaluation audits
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Append-only evaluation decisions. This source is admin-only.
          </p>
          {retrainingError ? (
            <div className="mt-4">
              <SectionError
                message={retrainingError}
                onRetry={() => {
                  setRetrainingError(null);
                  setRetrainingRevision((value) => value + 1);
                }}
              />
            </div>
          ) : retrainingPage === null ? (
            <div className="mt-4">
              <LoadingSkeleton label="Loading retraining audits" />
            </div>
          ) : retrainingPage.items.length ? (
            <div className="mt-4 overflow-x-auto rounded-lg border border-border bg-card">
              <table className="min-w-[900px] w-full text-left text-sm">
                <thead className="bg-muted text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3">Timestamp</th>
                    <th className="px-4 py-3">Actor</th>
                    <th className="px-4 py-3">Action</th>
                    <th className="px-4 py-3">Resource</th>
                    <th className="px-4 py-3">Outcome</th>
                    <th className="px-4 py-3">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {retrainingPage.items.map((item) => (
                    <tr className="border-t border-border" key={item.id}>
                      <td className="px-4 py-3">
                        {formatDate(item.decision.evaluated_at)}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {item.evaluated_by_user_id}
                      </td>
                      <td className="px-4 py-3">evaluate retraining</td>
                      <td className="px-4 py-3">
                        {item.decision.registered_model_name} /{" "}
                        {item.decision.source_model_version ?? "unresolved"}
                      </td>
                      <td className="px-4 py-3">
                        <IntelligenceStatus value={item.decision.decision_status} />
                      </td>
                      <td className="px-4 py-3">
                        <details>
                          <summary className="cursor-pointer font-semibold text-link">
                            Safe detail
                          </summary>
                          <div className="mt-2 max-w-sm text-xs text-secondary-foreground">
                            Trigger: {item.decision.trigger_type}. Mode:{" "}
                            {item.evaluation_mode}.{" "}
                            {item.decision.reasons.join(" ") || "No additional detail."}
                          </div>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="px-4 pb-4">
                <PaginationControls
                  limit={LIMIT}
                  offset={retrainingOffset}
                  onPageChange={setRetrainingOffset}
                  total={retrainingPage.total}
                />
              </div>
            </div>
          ) : (
            <div className="mt-4">
              <EmptyState
                title="No retraining audits"
                description="No retraining evaluations have been recorded."
              />
            </div>
          )}
        </section>
      ) : null}
    </section>
  );
}
