import { useEffect, useState, type ReactElement } from "react";
import { Link, useParams } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import { getMachine, type Machine } from "../../api/hierarchy";
import { listTimeline, type TimelinePage } from "../../api/operations";
import {
  Breadcrumbs,
  EmptyState,
  LoadingSkeleton,
  PaginationControls,
} from "../../components/hierarchy/ResourceStates";
import {
  OperationalError,
  formatOperationalDate,
  operationalInputClassName,
} from "../../components/operations/OperationalUi";
import { PageHeader } from "../../components/ui/PageHeader";

const LIMIT = 30;

export function MachineTimelinePage(): ReactElement {
  const { factoryId = "", machineId = "" } = useParams<{
    factoryId: string;
    machineId: string;
  }>();
  const [machine, setMachine] = useState<Machine | null>(null);
  const [page, setPage] = useState<TimelinePage | null>(null);
  const [offset, setOffset] = useState(0);
  const [eventType, setEventType] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.all([
      getMachine(machineId, controller.signal),
      listTimeline({
        eventType: eventType || undefined,
        limit: LIMIT,
        machineId,
        offset,
        signal: controller.signal,
      }),
    ])
      .then(([nextMachine, nextPage]) => {
        if (active) {
          setMachine(nextMachine);
          setPage(nextPage);
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
  }, [eventType, machineId, offset, revision]);

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
  if (!machine || !page) return <LoadingSkeleton label="Loading machine timeline" />;

  return (
    <section aria-labelledby="timeline-heading">
      <Breadcrumbs
        items={[
          { label: "Factories", to: "/factories" },
          { label: "Factory", to: `/factories/${factoryId}` },
          {
            label: machine.name,
            to: `/factories/${factoryId}/machines/${machine.id}`,
          },
          { label: "Timeline" },
        ]}
      />
      <PageHeader
        description="Operational history for this machine. Security audit history remains separate."
        eyebrow="Machine operations"
        headingId="timeline-heading"
        title={`${machine.name} timeline`}
      />
      <label className="mt-6 block max-w-sm text-sm font-semibold text-foreground">
        Event type
        <select
          className={operationalInputClassName}
          onChange={(event) => {
            setOffset(0);
            setEventType(event.target.value);
          }}
          value={eventType}
        >
          <option value="">All events</option>
          <option value="prediction.completed">Prediction completed</option>
          <option value="machine_risk.assessed">Machine risk assessed</option>
          <option value="alert.created">Alert created</option>
          <option value="alert.assign">Alert assigned</option>
          <option value="alert.acknowledge">Alert acknowledged</option>
          <option value="alert.escalate">Alert escalated</option>
          <option value="alert.resolve">Alert resolved</option>
          <option value="action.created">Action created</option>
          <option value="action.assigned">Action assigned</option>
          <option value="action.completed">Action completed</option>
          <option value="note.added">Note added</option>
          <option value="maintenance.feedback_submitted">Maintenance feedback</option>
        </select>
      </label>
      <div className="mt-6">
        {page.items.length === 0 ? (
          <EmptyState
            description="No operational events match this machine and filter."
            title="No timeline events"
          />
        ) : (
          <>
            <ol className="relative ml-3 border-l border-purple-300">
              {page.items.map((event) => (
                <li className="relative mb-5 ml-6" key={event.id}>
                  <span
                    aria-hidden="true"
                    className="absolute -left-[1.9rem] top-1 h-3 w-3 rounded-full bg-purple-600 ring-4 ring-purple-100"
                  />
                  <article className="rounded-lg border border-border bg-card p-4 shadow-panel">
                    <div className="flex flex-wrap justify-between gap-2">
                      <h2 className="font-semibold text-foreground">{event.title}</h2>
                      <time className="text-xs text-muted-foreground">
                        {formatOperationalDate(event.occurred_at)}
                      </time>
                    </div>
                    <p className="mt-1 text-sm text-secondary-foreground">
                      {event.detail}
                    </p>
                    <p className="mt-2 text-xs font-semibold uppercase text-eyebrow">
                      {event.event_type.replaceAll(".", " ")}
                    </p>
                    <div className="mt-3 flex gap-4 text-sm font-semibold">
                      {event.action_id ? (
                        <Link
                          className="text-link"
                          to={`/operations/actions/${event.action_id}`}
                        >
                          Open action
                        </Link>
                      ) : null}
                      {event.alert_id ? (
                        <Link
                          className="text-link"
                          to={`/monitoring/alerts/${event.alert_id}`}
                        >
                          Open alert
                        </Link>
                      ) : null}
                    </div>
                  </article>
                </li>
              ))}
            </ol>
            <PaginationControls
              limit={page.limit}
              offset={page.offset}
              onPageChange={setOffset}
              total={page.total}
            />
          </>
        )}
      </div>
    </section>
  );
}
