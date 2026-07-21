import { useEffect, useState, type ReactElement } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getPredictionEvent,
  submitPredictionOutcome,
  type PredictionEvent,
} from "../../api/predictions";
import {
  InlineError,
  InlineNotice,
  LoadingSkeleton,
  primaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import {
  IntelligenceStatus,
  KeyValues,
  formatDate,
  inputClassName,
  panelClassName,
} from "../../components/intelligence/IntelligenceUi";
import { PageHeader } from "../../components/ui/PageHeader";
import { useAuth } from "../../auth/useAuth";
import { isRequestCancelled } from "../../api/client";
export function PredictionEventDetailPage(): ReactElement {
  const { role } = useAuth();
  const { id = "" } = useParams<{ id: string }>();
  const [event, setEvent] = useState<PredictionEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actual, setActual] = useState("");
  const [source, setSource] = useState("manual-review");
  const [observed, setObserved] = useState("");
  const [mature, setMature] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (role === "operator") return;
    const c = new AbortController();
    let active = true;
    getPredictionEvent(id, c.signal)
      .then((value) => {
        if (active) {
          setEvent(value);
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (active && !isRequestCancelled(e, c.signal))
          setError(e instanceof Error ? e.message : "Event unavailable.");
      });
    return () => {
      active = false;
      c.abort();
    };
  }, [id, revision, role]);
  if (role === "operator")
    return (
      <InlineError
        message="Prediction-event detail is restricted to administrators and engineers."
        onRetry={() => history.back()}
      />
    );
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
  if (!event) return <LoadingSkeleton />;
  return (
    <section>
      <PageHeader
        eyebrow="Prediction event"
        headingId="event-heading"
        title={event.event_id}
        description={`${event.registered_model_name} · requested ${event.requested_model_reference}`}
        actions={<IntelligenceStatus value={event.status} />}
      />
      <div className="mt-6">
        <KeyValues
          items={[
            {
              label: "Resolved version",
              value: event.resolved_model_version ?? "Unresolved",
            },
            { label: "Task", value: event.trainer_key.task_type },
            {
              label: "Rows × features",
              value: `${event.row_count} × ${event.feature_count}`,
            },
            { label: "Duration", value: `${event.duration_ms.toFixed(2)} ms` },
            { label: "Created", value: formatDate(event.created_at) },
            { label: "Completed", value: formatDate(event.completed_at) },
          ]}
        />
      </div>
      {event.safe_error_message ? (
        <div className="mt-5">
          <InlineError
            message={event.safe_error_message}
            onRetry={() => setRevision((v) => v + 1)}
          />
        </div>
      ) : null}
      <div className="mt-5 flex flex-wrap gap-3">
        <Link
          className="font-semibold text-link"
          to={`/models/${encodeURIComponent(event.registered_model_name)}/versions/${encodeURIComponent(event.resolved_model_version ?? event.requested_model_reference)}`}
        >
          Model version
        </Link>
        <Link
          className="font-semibold text-link"
          to={`/monitoring/models/${encodeURIComponent(event.registered_model_name)}/versions/${encodeURIComponent(event.resolved_model_version ?? event.requested_model_reference)}`}
        >
          Monitoring
        </Link>
      </div>
      <form
        className={`${panelClassName} mt-6`}
        onSubmit={(e) => {
          e.preventDefault();
          const value = Number(actual);
          if (!Number.isFinite(value)) {
            setError("Actual value must be finite.");
            return;
          }
          void submitPredictionOutcome(id, {
            actual_value: value,
            observed_at: new Date(observed).toISOString(),
            source,
            label_maturity_at: new Date(mature).toISOString(),
            safe_metadata: {},
            external_reference_key: null,
          })
            .then(() =>
              setMessage(
                "Outcome submitted successfully. Outcome history is not available from the current API.",
              ),
            )
            .catch((caught: unknown) =>
              setError(caught instanceof Error ? caught.message : "Outcome failed."),
            );
        }}
      >
        <h2 className="text-lg font-semibold text-foreground">Submit actual outcome</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="text-sm">
            Actual value
            <input
              required
              type="number"
              step="any"
              className={inputClassName}
              value={actual}
              onChange={(e) => setActual(e.target.value)}
            />
          </label>
          <label className="text-sm">
            Source
            <input
              required
              className={inputClassName}
              value={source}
              onChange={(e) => setSource(e.target.value)}
            />
          </label>
          <label className="text-sm">
            Observed at
            <input
              required
              type="datetime-local"
              className={inputClassName}
              value={observed}
              onChange={(e) => setObserved(e.target.value)}
            />
          </label>
          <label className="text-sm">
            Label maturity at
            <input
              required
              type="datetime-local"
              className={inputClassName}
              value={mature}
              onChange={(e) => setMature(e.target.value)}
            />
          </label>
        </div>
        <button className={`${primaryButtonClassName} mt-4`} type="submit">
          Submit outcome
        </button>
        {message ? (
          <div className="mt-4">
            <InlineNotice>{message}</InlineNotice>
          </div>
        ) : null}
      </form>
    </section>
  );
}
