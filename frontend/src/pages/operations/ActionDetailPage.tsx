import { useEffect, useState, type FormEvent, type ReactElement } from "react";
import { Link, useParams } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import {
  acknowledgeOperationalAction,
  addActionNote,
  assignOperationalAction,
  getOperationalAction,
  listMaintenanceFeedback,
  listOperationalAssignees,
  listOperationalNotes,
  reopenOperationalAction,
  submitMaintenanceFeedback,
  transitionOperationalAction,
  type FeedbackOutcome,
  type MaintenanceFeedback,
  type OperationalAction,
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
  ActionSummaryCard,
  OperationalError,
  formatOperationalDate,
  operationalInputClassName,
  operationalPanelClassName,
} from "../../components/operations/OperationalUi";
import { buttonClassName } from "../../components/ui/buttonStyles";
import { PageHeader } from "../../components/ui/PageHeader";

export function ActionDetailPage(): ReactElement {
  const { actionId = "" } = useParams<{ actionId: string }>();
  const { role } = useAuth();
  const [action, setAction] = useState<OperationalAction | null>(null);
  const [notes, setNotes] = useState<readonly OperationalNote[]>([]);
  const [assignees, setAssignees] = useState<readonly OperationalAssignee[]>([]);
  const [feedback, setFeedback] = useState<readonly MaintenanceFeedback[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [mutationError, setMutationError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [note, setNote] = useState("");
  const [summary, setSummary] = useState("");
  const [assigneeId, setAssigneeId] = useState("");
  const [feedbackOutcome, setFeedbackOutcome] = useState<FeedbackOutcome>(
    "maintenance_performed",
  );
  const [feedbackSummary, setFeedbackSummary] = useState("");
  const canManage = hasProductCapability(role, "engineering.write");

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.all([
      getOperationalAction(actionId, controller.signal),
      listOperationalNotes({ actionId }, controller.signal),
      canManage ? listOperationalAssignees(controller.signal) : Promise.resolve([]),
      canManage
        ? listMaintenanceFeedback({
            actionId,
            limit: 100,
            signal: controller.signal,
          })
        : Promise.resolve({ items: [], limit: 100, offset: 0, total: 0 }),
    ])
      .then(([nextAction, nextNotes, nextAssignees, nextFeedback]) => {
        if (active) {
          setAction(nextAction);
          setNotes(nextNotes);
          setAssignees(nextAssignees);
          setFeedback(nextFeedback.items);
          setAssigneeId(nextAction.assigned_user_id ?? "");
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
  }, [actionId, canManage, revision]);

  const mutate = (operation: () => Promise<OperationalAction>): void => {
    setBusy(true);
    setMutationError(null);
    void operation()
      .then((value) => {
        setAction(value);
        setSummary("");
        setRevision((current) => current + 1);
      })
      .catch(setMutationError)
      .finally(() => setBusy(false));
  };

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
  if (!action) return <LoadingSkeleton label="Loading operational action" />;

  const addNote = (event: FormEvent): void => {
    event.preventDefault();
    setBusy(true);
    setMutationError(null);
    void addActionNote(action.id, note)
      .then((created) => {
        setNotes((items) => [...items, created]);
        setNote("");
      })
      .catch(setMutationError)
      .finally(() => setBusy(false));
  };

  const submitFeedback = (event: FormEvent): void => {
    event.preventDefault();
    setBusy(true);
    setMutationError(null);
    void submitMaintenanceFeedback({
      action_id: action.id,
      outcome: feedbackOutcome,
      summary: feedbackSummary,
    })
      .then((created) => {
        setFeedback((items) => [created, ...items]);
        setFeedbackSummary("");
      })
      .catch(setMutationError)
      .finally(() => setBusy(false));
  };

  return (
    <section aria-labelledby="action-heading">
      <Breadcrumbs
        items={[
          { label: "Required actions", to: "/operations/actions" },
          { label: action.title },
        ]}
      />
      <PageHeader
        description={action.recommended_action}
        eyebrow="Operational action"
        headingId="action-heading"
        title={action.title}
      />
      <div className="mt-6">
        <ActionSummaryCard action={action} />
      </div>
      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <section
          className={operationalPanelClassName}
          aria-labelledby="progress-heading"
        >
          <h2 className="text-lg font-semibold text-foreground" id="progress-heading">
            Progress action
          </h2>
          <p className="mt-1 text-sm text-secondary-foreground">
            Status changes are validated, versioned, and added to the operational
            timeline.
          </p>
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
            Completion, block, or reopen summary
            <textarea
              className={operationalInputClassName}
              maxLength={2000}
              onChange={(event) => setSummary(event.target.value)}
              rows={3}
              value={summary}
            />
          </label>
          <div className="mt-4 flex flex-wrap gap-2">
            {canManage && assigneeId ? (
              <button
                className={buttonClassName("secondary")}
                disabled={busy || assigneeId === action.assigned_user_id}
                onClick={() =>
                  mutate(() =>
                    assignOperationalAction(action.id, assigneeId, action.version),
                  )
                }
                type="button"
              >
                Assign
              </button>
            ) : null}
            {["open", "assigned"].includes(action.status) ? (
              <button
                className={buttonClassName("secondary")}
                disabled={busy}
                onClick={() =>
                  mutate(() =>
                    acknowledgeOperationalAction(
                      action.id,
                      action.version,
                      summary || undefined,
                    ),
                  )
                }
                type="button"
              >
                Acknowledge
              </button>
            ) : null}
            {action.status === "assigned" ? (
              <button
                className={buttonClassName("primary")}
                disabled={busy}
                onClick={() =>
                  mutate(() =>
                    transitionOperationalAction(
                      action.id,
                      "in_progress",
                      action.version,
                    ),
                  )
                }
                type="button"
              >
                Start work
              </button>
            ) : null}
            {["in_progress", "blocked"].includes(action.status) ? (
              <>
                {action.status === "in_progress" ? (
                  <button
                    className={buttonClassName("secondary")}
                    disabled={busy}
                    onClick={() =>
                      mutate(() =>
                        transitionOperationalAction(
                          action.id,
                          "blocked",
                          action.version,
                          summary || undefined,
                        ),
                      )
                    }
                    type="button"
                  >
                    Mark blocked
                  </button>
                ) : (
                  <button
                    className={buttonClassName("primary")}
                    disabled={busy}
                    onClick={() =>
                      mutate(() =>
                        transitionOperationalAction(
                          action.id,
                          "in_progress",
                          action.version,
                        ),
                      )
                    }
                    type="button"
                  >
                    Resume work
                  </button>
                )}
                {action.status === "in_progress" ? (
                  <button
                    className={buttonClassName("primary")}
                    disabled={busy || summary.trim() === ""}
                    onClick={() =>
                      mutate(() =>
                        transitionOperationalAction(
                          action.id,
                          "completed",
                          action.version,
                          summary,
                        ),
                      )
                    }
                    type="button"
                  >
                    Complete
                  </button>
                ) : null}
              </>
            ) : null}
            {canManage && ["completed", "cancelled"].includes(action.status) ? (
              <button
                className={buttonClassName("secondary")}
                disabled={busy || summary.trim() === ""}
                onClick={() =>
                  mutate(() =>
                    reopenOperationalAction(action.id, action.version, summary),
                  )
                }
                type="button"
              >
                Reopen explicitly
              </button>
            ) : null}
          </div>
          {mutationError ? (
            <div className="mt-4">
              <OperationalError error={mutationError} />
            </div>
          ) : null}
        </section>

        <section className={operationalPanelClassName} aria-labelledby="notes-heading">
          <h2 className="text-lg font-semibold text-foreground" id="notes-heading">
            Notes
          </h2>
          <ol className="mt-4 space-y-3">
            {notes.length === 0 ? (
              <li className="text-sm text-secondary-foreground">
                No notes have been added.
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
              Add {role === "operator" ? "operator" : "engineer"} note
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

      <section
        className={`${operationalPanelClassName} mt-6`}
        aria-labelledby="feedback-heading"
      >
        <h2 className="text-lg font-semibold text-foreground" id="feedback-heading">
          Maintenance feedback
        </h2>
        <p className="mt-1 text-sm text-secondary-foreground">
          This is retained as human feedback for later evaluation. It does not
          automatically retrain a model.
        </p>
        {feedback.length > 0 ? (
          <ol className="mt-4 space-y-3">
            {feedback.map((item) => (
              <li className="rounded-md bg-elevated p-3" key={item.id}>
                <p className="text-sm font-semibold capitalize text-foreground">
                  {item.outcome.replaceAll("_", " ")}
                </p>
                <p className="mt-1 text-sm text-secondary-foreground">{item.summary}</p>
                <time className="mt-1 block text-xs text-muted-foreground">
                  {formatOperationalDate(item.created_at)}
                </time>
              </li>
            ))}
          </ol>
        ) : null}
        <form className="mt-4 grid gap-4 sm:grid-cols-2" onSubmit={submitFeedback}>
          <label className="text-sm font-semibold text-foreground">
            Outcome
            <select
              className={operationalInputClassName}
              onChange={(event) =>
                setFeedbackOutcome(event.target.value as FeedbackOutcome)
              }
              value={feedbackOutcome}
            >
              <option value="true_issue">True issue</option>
              <option value="false_alarm">False alarm</option>
              <option value="sensor_fault">Sensor fault</option>
              <option value="maintenance_performed">Maintenance performed</option>
              <option value="no_action_required">No action required</option>
              <option value="machine_stopped">Machine stopped</option>
              <option value="other">Other</option>
            </select>
          </label>
          <label className="text-sm font-semibold text-foreground">
            Human feedback summary
            <textarea
              className={operationalInputClassName}
              maxLength={4000}
              onChange={(event) => setFeedbackSummary(event.target.value)}
              required
              rows={3}
              value={feedbackSummary}
            />
          </label>
          <button
            className={buttonClassName("secondary")}
            disabled={busy}
            type="submit"
          >
            Submit immutable feedback
          </button>
        </form>
      </section>

      <div className="mt-6 flex flex-wrap gap-4 text-sm font-semibold">
        <Link
          className="text-link"
          to={`/factories/${action.factory_id}/machines/${action.machine_id}`}
        >
          Machine detail
        </Link>
        <Link
          className="text-link"
          to={`/factories/${action.factory_id}/machines/${action.machine_id}/timeline`}
        >
          Machine timeline
        </Link>
        {action.related_alert_id ? (
          <Link
            className="text-link"
            to={`/monitoring/alerts/${action.related_alert_id}`}
          >
            Related alert
          </Link>
        ) : null}
      </div>
    </section>
  );
}
