import { useEffect, useState, type FormEvent, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import {
  listFactories,
  listMachines,
  type Factory,
  type Machine,
} from "../../api/hierarchy";
import {
  createOperationalAction,
  listOperationalActions,
  type ActionPriority,
  type ActionStatus,
  type OperationalActionPage,
} from "../../api/operations";
import { useAuth } from "../../auth/useAuth";
import { hasProductCapability } from "../../auth/permissions";
import {
  EmptyState,
  LoadingSkeleton,
  PaginationControls,
} from "../../components/hierarchy/ResourceStates";
import {
  ActionSummaryCard,
  OperationalError,
  operationalInputClassName,
  operationalPanelClassName,
} from "../../components/operations/OperationalUi";
import { buttonClassName } from "../../components/ui/buttonStyles";
import { PageHeader } from "../../components/ui/PageHeader";

const LIMIT = 20;

export function RequiredActionsPage(): ReactElement {
  const { role } = useAuth();
  const [page, setPage] = useState<OperationalActionPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [priority, setPriority] = useState<ActionPriority | "">("");
  const [status, setStatus] = useState<ActionStatus | "">("");
  const [overdue, setOverdue] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [revision, setRevision] = useState(0);
  const [showCreate, setShowCreate] = useState(false);
  const canManage = hasProductCapability(role, "engineering.write");

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    listOperationalActions({
      limit: LIMIT,
      offset,
      overdue: overdue || undefined,
      priority: priority || undefined,
      signal: controller.signal,
      status: status || undefined,
    })
      .then((value) => {
        if (active) {
          setPage(value);
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
  }, [offset, overdue, priority, revision, status]);

  return (
    <section aria-labelledby="actions-heading">
      <PageHeader
        actions={
          canManage ? (
            <button
              className={buttonClassName("primary")}
              onClick={() => setShowCreate((value) => !value)}
              type="button"
            >
              {showCreate ? "Close action form" : "Create action"}
            </button>
          ) : undefined
        }
        description={
          role === "operator"
            ? "Your assigned work and urgent unassigned items available to operators."
            : "Prioritized work across the company, including overdue and unassigned actions."
        }
        eyebrow="What should I do now?"
        headingId="actions-heading"
        title="Required actions"
      />

      {showCreate && canManage ? (
        <CreateActionForm
          onCreated={() => {
            setShowCreate(false);
            setOffset(0);
            setRevision((value) => value + 1);
          }}
        />
      ) : null}

      <div
        aria-label="Action filters"
        className={`${operationalPanelClassName} mt-6 grid gap-4 sm:grid-cols-3`}
      >
        <label className="text-sm font-semibold text-foreground">
          Priority
          <select
            className={operationalInputClassName}
            onChange={(event) => {
              setOffset(0);
              setPriority(event.target.value as ActionPriority | "");
            }}
            value={priority}
          >
            <option value="">All priorities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </label>
        <label className="text-sm font-semibold text-foreground">
          Status
          <select
            className={operationalInputClassName}
            onChange={(event) => {
              setOffset(0);
              setStatus(event.target.value as ActionStatus | "");
            }}
            value={status}
          >
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="assigned">Assigned</option>
            <option value="in_progress">In progress</option>
            <option value="blocked">Blocked</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </label>
        <label className="flex min-h-10 items-center gap-3 self-end rounded-md border border-border bg-elevated px-3 py-2 text-sm font-semibold text-foreground">
          <input
            checked={overdue}
            onChange={(event) => {
              setOffset(0);
              setOverdue(event.target.checked);
            }}
            type="checkbox"
          />
          Overdue only
        </label>
      </div>

      <div className="mt-6">
        {error ? (
          <OperationalError
            error={error}
            onRetry={() => {
              setError(null);
              setRevision((value) => value + 1);
            }}
          />
        ) : page === null ? (
          <LoadingSkeleton label="Loading required actions" />
        ) : page.items.length === 0 ? (
          <EmptyState
            description={
              role === "operator"
                ? "There are no assigned or urgent operational actions requiring your attention."
                : "There are no operational actions matching the current filters."
            }
            title="No pending operational actions"
          />
        ) : (
          <div className="space-y-4">
            {page.items.map((action) => (
              <ActionSummaryCard
                action={action}
                footer={
                  <Link
                    className="text-sm font-semibold text-link"
                    to={`/operations/actions/${action.id}`}
                  >
                    Open action
                  </Link>
                }
                key={action.id}
              />
            ))}
            <PaginationControls
              limit={page.limit}
              offset={page.offset}
              onPageChange={setOffset}
              total={page.total}
            />
          </div>
        )}
      </div>
    </section>
  );
}

function CreateActionForm({
  onCreated,
}: {
  readonly onCreated: () => void;
}): ReactElement {
  const [factoryId, setFactoryId] = useState("");
  const [machineId, setMachineId] = useState("");
  const [title, setTitle] = useState("");
  const [reason, setReason] = useState("");
  const [recommendedAction, setRecommendedAction] = useState("");
  const [priority, setPriority] = useState<ActionPriority>("high");
  const [dueAt, setDueAt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [factories, setFactories] = useState<readonly Factory[]>([]);
  const [machines, setMachines] = useState<readonly Machine[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    listFactories({ limit: 100, signal: controller.signal })
      .then((page) => {
        setFactories(page.items);
        setFactoryId((current) => current || page.items[0]?.id || "");
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal)) setError(caught);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!factoryId) return;
    const controller = new AbortController();
    listMachines(factoryId, { limit: 100, signal: controller.signal })
      .then((page) => {
        setMachines(page.items);
        setMachineId((current) =>
          page.items.some((item) => item.id === current)
            ? current
            : page.items[0]?.id || "",
        );
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal)) setError(caught);
      });
    return () => controller.abort();
  }, [factoryId]);

  const submit = (event: FormEvent): void => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    void createOperationalAction({
      due_at: dueAt ? new Date(dueAt).toISOString() : undefined,
      factory_id: factoryId,
      machine_id: machineId,
      priority,
      reason,
      recommended_action: recommendedAction,
      title,
    })
      .then(onCreated)
      .catch(setError)
      .finally(() => setBusy(false));
  };

  return (
    <form
      className={`${operationalPanelClassName} mt-6 grid gap-4 sm:grid-cols-2`}
      onSubmit={submit}
    >
      <div className="sm:col-span-2">
        <h2 className="text-lg font-semibold text-foreground">
          Create operational action
        </h2>
        <p className="mt-1 text-sm text-secondary-foreground">
          Choose an authorized machine. The server verifies company ownership.
        </p>
      </div>
      <label className="text-sm font-semibold text-foreground">
        Factory ID
        <select
          className={operationalInputClassName}
          onChange={(event) => setFactoryId(event.target.value)}
          required
          value={factoryId}
        >
          {factories.map((factory) => (
            <option key={factory.id} value={factory.id}>
              {factory.name}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm font-semibold text-foreground">
        Machine ID
        <select
          className={operationalInputClassName}
          onChange={(event) => setMachineId(event.target.value)}
          required
          value={machineId}
        >
          {machines.map((machine) => (
            <option key={machine.id} value={machine.id}>
              {machine.name}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm font-semibold text-foreground sm:col-span-2">
        Title
        <input
          className={operationalInputClassName}
          maxLength={255}
          onChange={(event) => setTitle(event.target.value)}
          required
          value={title}
        />
      </label>
      <label className="text-sm font-semibold text-foreground">
        Reason
        <textarea
          className={operationalInputClassName}
          maxLength={2000}
          onChange={(event) => setReason(event.target.value)}
          required
          rows={4}
          value={reason}
        />
      </label>
      <label className="text-sm font-semibold text-foreground">
        Recommended action
        <textarea
          className={operationalInputClassName}
          maxLength={2000}
          onChange={(event) => setRecommendedAction(event.target.value)}
          required
          rows={4}
          value={recommendedAction}
        />
      </label>
      <label className="text-sm font-semibold text-foreground">
        Priority
        <select
          className={operationalInputClassName}
          onChange={(event) => setPriority(event.target.value as ActionPriority)}
          value={priority}
        >
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </label>
      <label className="text-sm font-semibold text-foreground">
        Due time (optional)
        <input
          className={operationalInputClassName}
          onChange={(event) => setDueAt(event.target.value)}
          type="datetime-local"
          value={dueAt}
        />
      </label>
      {error ? (
        <div className="sm:col-span-2">
          <OperationalError error={error} />
        </div>
      ) : null}
      <div className="sm:col-span-2">
        <button className={buttonClassName("primary")} disabled={busy} type="submit">
          {busy ? "Creating…" : "Create action"}
        </button>
      </div>
    </form>
  );
}
