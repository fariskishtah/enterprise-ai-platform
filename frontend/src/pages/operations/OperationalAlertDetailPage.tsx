import { useEffect, useState, type FormEvent, type ReactElement } from "react";
import { Link, useParams } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import {
  addAlertNote,
  getOperationalAlert,
  listOperationalAssignees,
  listOperationalNotes,
  submitMaintenanceFeedback,
  transitionOperationalAlert,
  type FeedbackOutcome,
  type OperationalAlert,
  type OperationalAssignee,
  type OperationalNote,
} from "../../api/operations";
import { useAuth } from "../../auth/useAuth";
import { hasProductCapability } from "../../auth/permissions";
import {
  Breadcrumbs,
  LoadingSkeleton,
} from "../../components/hierarchy/ResourceStates";
import {
  ActionStatusBadge,
  OperationalError,
  formatOperationalDate,
  operationalInputClassName,
  operationalPanelClassName,
} from "../../components/operations/OperationalUi";
import { buttonClassName } from "../../components/ui/buttonStyles";
import { PageHeader } from "../../components/ui/PageHeader";
import {
  readFavorites,
  recordRecentResource,
  toggleFavoriteResource,
} from "../../product/resourcePreferences";

export function OperationalAlertDetailPage(): ReactElement {
  const { id = "" } = useParams<{ id: string }>();
  const { role, user } = useAuth();
  const [alert, setAlert] = useState<OperationalAlert | null>(null);
  const [notes, setNotes] = useState<readonly OperationalNote[]>([]);
  const [assignees, setAssignees] = useState<readonly OperationalAssignee[]>([]);
  const [assigneeId, setAssigneeId] = useState("");
  const [note, setNote] = useState("");
  const [summary, setSummary] = useState("");
  const [classification, setClassification] = useState("maintenance_performed");
  const [error, setError] = useState<unknown>(null);
  const [mutationError, setMutationError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [favorite, setFavorite] = useState(false);
  const canManage = hasProductCapability(role, "engineering.write");

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.all([
      getOperationalAlert(id, controller.signal),
      listOperationalNotes({ alertId: id }, controller.signal),
      canManage ? listOperationalAssignees(controller.signal) : Promise.resolve([]),
    ])
      .then(([nextAlert, nextNotes, nextAssignees]) => {
        if (active) {
          if (user !== null) {
            recordRecentResource(user.id, {
              id: nextAlert.id,
              label: nextAlert.title,
              path: `/monitoring/alerts/${nextAlert.id}`,
              type: "alert",
            });
            setFavorite(
              readFavorites(user.id).some(
                (item) => item.type === "alert" && item.id === nextAlert.id,
              ),
            );
          }
          setAlert(nextAlert);
          setNotes(nextNotes);
          setAssignees(nextAssignees);
          setAssigneeId(nextAlert.assigned_user_id ?? "");
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (active && !isRequestCancelled(caught, controller.signal)) setError(caught);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [canManage, id, revision, user]);

  if (error)
    return (
      <OperationalError
        error={error}
        onRetry={() => {
          setError(null);
          setRevision((value) => value + 1);
        }}
      />
    );
  if (!alert) return <LoadingSkeleton label="Loading alert detail" />;

  const transition = (
    kind: "assign" | "acknowledge" | "start" | "escalate" | "resolve" | "reopen",
  ): void => {
    if (
      ["resolve", "reopen"].includes(kind) &&
      !window.confirm(`Confirm alert ${kind}? This transition is audited.`)
    )
      return;
    setBusy(true);
    setMutationError(null);
    void transitionOperationalAlert(alert.id, {
      assigned_user_id: kind === "assign" ? assigneeId : undefined,
      expected_version: alert.lifecycle_version,
      note:
        kind === "acknowledge" || kind === "escalate"
          ? summary || undefined
          : undefined,
      reopen_reason: kind === "reopen" ? summary : undefined,
      resolution_classification: kind === "resolve" ? classification : undefined,
      resolution_summary: kind === "resolve" ? summary : undefined,
      transition: kind,
    })
      .then((value) => {
        setAlert(value);
        setNote("");
        setSummary("");
        setRevision((current) => current + 1);
      })
      .catch(setMutationError)
      .finally(() => setBusy(false));
  };

  const addNote = (event: FormEvent): void => {
    event.preventDefault();
    setBusy(true);
    setMutationError(null);
    void addAlertNote(alert.id, note)
      .then((created) => {
        setNotes((items) => [...items, created]);
        setNote("");
      })
      .catch(setMutationError)
      .finally(() => setBusy(false));
  };

  const feedback = (event: FormEvent): void => {
    event.preventDefault();
    setBusy(true);
    setMutationError(null);
    void submitMaintenanceFeedback({
      alert_id: alert.id,
      outcome: classification.replace(
        "sensor_issue",
        "sensor_fault",
      ) as FeedbackOutcome,
      summary,
    })
      .then(() => setSummary(""))
      .catch(setMutationError)
      .finally(() => setBusy(false));
  };

  return (
    <section aria-labelledby="alert-heading">
      <Breadcrumbs
        items={[{ label: "Alerts", to: "/monitoring/alerts" }, { label: alert.title }]}
      />
      <PageHeader
        actions={
          <div className="flex flex-wrap gap-2">
            <button
              aria-pressed={favorite}
              className={buttonClassName("secondary")}
              onClick={() => {
                if (user === null) return;
                setFavorite(
                  toggleFavoriteResource(user.id, {
                    id: alert.id,
                    label: alert.title,
                    path: `/monitoring/alerts/${alert.id}`,
                    type: "alert",
                  }),
                );
              }}
              type="button"
            >
              {favorite ? "Remove favorite" : "Add favorite"}
            </button>
            <span className="rounded-full border border-orange-300 bg-orange-50 px-2.5 py-1 text-xs font-semibold capitalize text-orange-900">
              {alert.severity}
            </span>
            <ActionStatusBadge status={alert.status} />
          </div>
        }
        description={alert.safe_summary}
        eyebrow="Operational alert"
        headingId="alert-heading"
        title={alert.title}
      />
      <dl className={`${operationalPanelClassName} mt-6 grid gap-4 sm:grid-cols-3`}>
        <div>
          <dt className="text-xs font-semibold uppercase text-muted-foreground">
            First detected
          </dt>
          <dd className="mt-1 text-sm text-foreground">
            {formatOperationalDate(alert.first_detected_at)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-muted-foreground">
            Last detected
          </dt>
          <dd className="mt-1 text-sm text-foreground">
            {formatOperationalDate(alert.last_detected_at)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-muted-foreground">
            Occurrences
          </dt>
          <dd className="mt-1 text-sm text-foreground">{alert.occurrence_count}</dd>
        </div>
      </dl>
      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <section className={operationalPanelClassName}>
          <h2 className="text-lg font-semibold text-foreground">Alert lifecycle</h2>
          {canManage ? (
            <label className="mt-4 block text-sm font-semibold text-foreground">
              Assignee
              <select
                className={operationalInputClassName}
                onChange={(event) => setAssigneeId(event.target.value)}
                value={assigneeId}
              >
                <option value="">Select an active company user</option>
                {assignees.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.email} · {item.role}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label className="mt-4 block text-sm font-semibold text-foreground">
            Note, resolution summary, or reopen reason
            <textarea
              className={operationalInputClassName}
              maxLength={2000}
              onChange={(event) => setSummary(event.target.value)}
              rows={3}
              value={summary}
            />
          </label>
          <label className="mt-4 block text-sm font-semibold text-foreground">
            Resolution classification
            <select
              className={operationalInputClassName}
              onChange={(event) => setClassification(event.target.value)}
              value={classification}
            >
              <option value="true_issue">True issue</option>
              <option value="false_alarm">False alarm</option>
              <option value="sensor_issue">Sensor issue</option>
              <option value="maintenance_performed">Maintenance performed</option>
              <option value="no_action_required">No action required</option>
            </select>
          </label>
          <div className="mt-4 flex flex-wrap gap-2">
            {canManage && assigneeId ? (
              <button
                className={buttonClassName("secondary")}
                disabled={busy || assigneeId === alert.assigned_user_id}
                onClick={() => transition("assign")}
                type="button"
              >
                Assign
              </button>
            ) : null}
            {alert.status === "open" ? (
              <button
                className={buttonClassName("secondary")}
                disabled={busy}
                onClick={() => transition("acknowledge")}
                type="button"
              >
                Acknowledge
              </button>
            ) : null}
            {["acknowledged", "escalated"].includes(alert.status) ? (
              <button
                className={buttonClassName("primary")}
                disabled={busy}
                onClick={() => transition("start")}
                type="button"
              >
                Start investigation
              </button>
            ) : null}
            {alert.status !== "resolved" ? (
              <button
                className={buttonClassName("secondary")}
                disabled={busy}
                onClick={() => transition("escalate")}
                type="button"
              >
                Escalate
              </button>
            ) : null}
            {alert.status === "in_progress" && canManage ? (
              <button
                className={buttonClassName("primary")}
                disabled={busy || summary.trim() === ""}
                onClick={() => transition("resolve")}
                type="button"
              >
                Resolve alert
              </button>
            ) : null}
            {alert.status === "resolved" && canManage ? (
              <button
                className={buttonClassName("secondary")}
                disabled={busy || summary.trim() === ""}
                onClick={() => transition("reopen")}
                type="button"
              >
                Reopen alert
              </button>
            ) : null}
          </div>
          {mutationError ? (
            <div className="mt-4">
              <OperationalError error={mutationError} />
            </div>
          ) : null}
        </section>
        <section className={operationalPanelClassName}>
          <h2 className="text-lg font-semibold text-foreground">Notes</h2>
          <ol className="mt-4 space-y-3">
            {notes.length === 0 ? (
              <li className="text-sm text-secondary-foreground">
                No operator or engineer notes have been added.
              </li>
            ) : (
              notes.map((item) => (
                <li className="rounded-md bg-elevated p-3" key={item.id}>
                  <p className="text-sm text-foreground">{item.body}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {item.kind} · {formatOperationalDate(item.created_at)}
                  </p>
                </li>
              ))
            )}
          </ol>
          <form className="mt-4" onSubmit={addNote}>
            <label className="text-sm font-semibold text-foreground">
              Add a separate note
              <textarea
                className={operationalInputClassName}
                maxLength={4000}
                onChange={(event) => setNote(event.target.value)}
                required
                rows={3}
                value={note}
              />
            </label>
            <button
              className={`${buttonClassName("secondary")} mt-3`}
              disabled={busy}
              type="submit"
            >
              Add note
            </button>
          </form>
        </section>
      </div>
      <form className={`${operationalPanelClassName} mt-6`} onSubmit={feedback}>
        <h2 className="font-semibold text-foreground">Record maintenance feedback</h2>
        <p className="mt-1 text-sm text-secondary-foreground">
          This human feedback is immutable and does not trigger automatic retraining.
        </p>
        <button
          className={`${buttonClassName("secondary")} mt-4`}
          disabled={busy || summary.trim() === ""}
          type="submit"
        >
          Record current classification and summary
        </button>
      </form>
      {alert.machine_id && alert.factory_id ? (
        <div className="mt-6 flex gap-4 text-sm font-semibold">
          <Link
            className="text-link"
            to={`/factories/${alert.factory_id}/machines/${alert.machine_id}`}
          >
            Machine detail
          </Link>
          <Link
            className="text-link"
            to={`/factories/${alert.factory_id}/machines/${alert.machine_id}/timeline`}
          >
            Machine timeline
          </Link>
        </div>
      ) : null}
    </section>
  );
}
