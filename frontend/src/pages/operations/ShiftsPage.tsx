import { useEffect, useState, type FormEvent, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import { listFactories, type Factory } from "../../api/hierarchy";
import {
  listShifts,
  startShift,
  type ShiftHandover,
  type ShiftPage,
} from "../../api/operations";
import {
  EmptyState,
  LoadingSkeleton,
  PaginationControls,
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

const LIMIT = 20;

export function ShiftsPage(): ReactElement {
  const [page, setPage] = useState<ShiftPage | null>(null);
  const [factories, setFactories] = useState<readonly Factory[]>([]);
  const [offset, setOffset] = useState(0);
  const [factoryId, setFactoryId] = useState("");
  const [teamLabel, setTeamLabel] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [mutationError, setMutationError] = useState<unknown>(null);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.all([
      listShifts({ limit: LIMIT, offset, signal: controller.signal }),
      listFactories({ limit: 100, signal: controller.signal }),
    ])
      .then(([nextPage, nextFactories]) => {
        if (active) {
          setPage(nextPage);
          setFactories(nextFactories.items);
          setFactoryId((current) => current || nextFactories.items[0]?.id || "");
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

  const submit = (event: FormEvent): void => {
    event.preventDefault();
    setBusy(true);
    setMutationError(null);
    void startShift(factoryId, teamLabel)
      .then(() => {
        setTeamLabel("");
        setOffset(0);
        setRevision((value) => value + 1);
      })
      .catch(setMutationError)
      .finally(() => setBusy(false));
  };

  return (
    <section aria-labelledby="shifts-heading">
      <PageHeader
        description="Start a lightweight factory shift, capture unresolved work, and provide an auditable handover."
        eyebrow="Operations"
        headingId="shifts-heading"
        title="Shift handover"
      />
      <form
        className={`${operationalPanelClassName} mt-6 grid gap-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end`}
        onSubmit={submit}
      >
        <label className="text-sm font-semibold text-foreground">
          Factory
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
          Operator or team label
          <input
            className={operationalInputClassName}
            maxLength={128}
            onChange={(event) => setTeamLabel(event.target.value)}
            placeholder="Day shift"
            value={teamLabel}
          />
        </label>
        <button
          className={buttonClassName("primary")}
          disabled={busy || factoryId === ""}
          type="submit"
        >
          {busy ? "Starting…" : "Start shift"}
        </button>
        {mutationError ? (
          <div className="sm:col-span-3">
            <OperationalError error={mutationError} />
          </div>
        ) : null}
      </form>
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
          <LoadingSkeleton label="Loading shifts" />
        ) : page.items.length === 0 ? (
          <EmptyState
            description="Start a shift to record operational activity and prepare a handover."
            title="No shifts recorded"
          />
        ) : (
          <>
            <div className="grid gap-4 lg:grid-cols-2">
              {page.items.map((shift) => (
                <ShiftCard key={shift.id} shift={shift} />
              ))}
            </div>
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

function ShiftCard({ shift }: { readonly shift: ShiftHandover }): ReactElement {
  return (
    <article className={operationalPanelClassName}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase text-eyebrow">
            {shift.team_label || "Factory shift"}
          </p>
          <h2 className="mt-1 font-semibold text-foreground">
            Started {formatOperationalDate(shift.started_at)}
          </h2>
        </div>
        <ActionStatusBadge status={shift.status} />
      </div>
      <p className="mt-3 line-clamp-2 text-sm text-secondary-foreground">
        {shift.handover_notes ?? "Handover notes will be captured when the shift ends."}
      </p>
      <Link
        className="mt-4 inline-block text-sm font-semibold text-link"
        to={`/operations/shifts/${shift.id}`}
      >
        Open handover
      </Link>
    </article>
  );
}
