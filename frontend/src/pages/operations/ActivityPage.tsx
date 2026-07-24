import { useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import { listTimeline, type TimelinePage } from "../../api/operations";
import {
  EmptyState,
  LoadingSkeleton,
  PaginationControls,
} from "../../components/hierarchy/ResourceStates";
import {
  OperationalError,
  formatOperationalDate,
} from "../../components/operations/OperationalUi";
import { PageHeader } from "../../components/ui/PageHeader";

const LIMIT = 30;

export function ActivityPage(): ReactElement {
  const [page, setPage] = useState<TimelinePage | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    listTimeline({ limit: LIMIT, offset, signal: controller.signal })
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
  }, [offset, revision]);

  return (
    <section aria-labelledby="activity-heading">
      <PageHeader
        description="Recent company-scoped machine, alert, action, note, feedback, and shift events."
        eyebrow="Operational history"
        headingId="activity-heading"
        title="Activity"
      />
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
          <LoadingSkeleton label="Loading operational activity" />
        ) : page.items.length === 0 ? (
          <EmptyState
            description="Operational events will appear after alerts, actions, notes, feedback, or shifts are recorded."
            title="No recent operational activity"
          />
        ) : (
          <>
            <ol className="space-y-3">
              {page.items.map((event) => (
                <li
                  className="rounded-lg border border-border bg-card p-5 shadow-panel"
                  key={event.id}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-eyebrow">
                        {event.event_type.replaceAll(".", " ")}
                      </p>
                      <h2 className="mt-1 font-semibold text-foreground">
                        {event.title}
                      </h2>
                      <p className="mt-1 text-sm text-secondary-foreground">
                        {event.detail}
                      </p>
                    </div>
                    <time className="text-xs text-muted-foreground">
                      {formatOperationalDate(event.occurred_at)}
                    </time>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-4 text-sm font-semibold">
                    <Link
                      className="text-link"
                      to={`/factories/${event.factory_id}/machines/${event.machine_id}/timeline`}
                    >
                      Machine timeline
                    </Link>
                    {event.action_id ? (
                      <Link
                        className="text-link"
                        to={`/operations/actions/${event.action_id}`}
                      >
                        Action
                      </Link>
                    ) : null}
                    {event.alert_id ? (
                      <Link
                        className="text-link"
                        to={`/monitoring/alerts/${event.alert_id}`}
                      >
                        Alert
                      </Link>
                    ) : null}
                  </div>
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
