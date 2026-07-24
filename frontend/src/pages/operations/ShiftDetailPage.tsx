import { useEffect, useState, type FormEvent, type ReactElement } from "react";
import { useParams } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import {
  acknowledgeShift,
  endShift,
  getShift,
  type ShiftHandover,
} from "../../api/operations";
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

function snapshotCount(
  snapshot: Readonly<Record<string, unknown>>,
  key: string,
): number {
  const value = snapshot[key];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function ShiftDetailPage(): ReactElement {
  const { shiftId = "" } = useParams<{ shiftId: string }>();
  const [shift, setShift] = useState<ShiftHandover | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [mutationError, setMutationError] = useState<unknown>(null);
  const [handoverNotes, setHandoverNotes] = useState("");
  const [unresolved, setUnresolved] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    getShift(shiftId, controller.signal)
      .then((value) => {
        if (active) {
          setShift(value);
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
  }, [revision, shiftId]);

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
  if (!shift) return <LoadingSkeleton label="Loading shift handover" />;

  const end = (event: FormEvent): void => {
    event.preventDefault();
    setBusy(true);
    setMutationError(null);
    void endShift(shift.id, handoverNotes, unresolved)
      .then(setShift)
      .catch(setMutationError)
      .finally(() => setBusy(false));
  };
  const acknowledge = (): void => {
    setBusy(true);
    setMutationError(null);
    void acknowledgeShift(shift.id)
      .then(setShift)
      .catch(setMutationError)
      .finally(() => setBusy(false));
  };

  return (
    <section aria-labelledby="shift-heading">
      <Breadcrumbs
        items={[
          { label: "Shift handovers", to: "/operations/shifts" },
          { label: shift.team_label || "Shift detail" },
        ]}
      />
      <PageHeader
        actions={
          <div className="flex gap-2 print:hidden">
            <ActionStatusBadge status={shift.status} />
            <button
              className={buttonClassName("secondary")}
              onClick={() => window.print()}
              type="button"
            >
              Print handover
            </button>
          </div>
        }
        description="Printable operational summary with unresolved items and next-shift acknowledgement."
        eyebrow="Shift handover"
        headingId="shift-heading"
        title={shift.team_label || "Factory shift"}
      />
      <dl className={`${operationalPanelClassName} mt-6 grid gap-4 sm:grid-cols-3`}>
        <div>
          <dt className="text-xs font-semibold uppercase text-muted-foreground">
            Started
          </dt>
          <dd className="mt-1 text-sm text-foreground">
            {formatOperationalDate(shift.started_at)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-muted-foreground">
            Ended
          </dt>
          <dd className="mt-1 text-sm text-foreground">
            {formatOperationalDate(shift.ended_at)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase text-muted-foreground">
            Next shift acknowledged
          </dt>
          <dd className="mt-1 text-sm text-foreground">
            {formatOperationalDate(shift.acknowledged_at)}
          </dd>
        </div>
      </dl>
      {shift.status === "active" ? (
        <form className={`${operationalPanelClassName} mt-6`} onSubmit={end}>
          <h2 className="text-lg font-semibold text-foreground">End shift</h2>
          <label className="mt-4 block text-sm font-semibold text-foreground">
            Handover notes
            <textarea
              className={operationalInputClassName}
              maxLength={4000}
              onChange={(event) => setHandoverNotes(event.target.value)}
              required
              rows={4}
              value={handoverNotes}
            />
          </label>
          <label className="mt-4 block text-sm font-semibold text-foreground">
            Unresolved items
            <textarea
              className={operationalInputClassName}
              maxLength={4000}
              onChange={(event) => setUnresolved(event.target.value)}
              rows={3}
              value={unresolved}
            />
          </label>
          <button
            className={`${buttonClassName("primary")} mt-4`}
            disabled={busy}
            type="submit"
          >
            End shift and save handover
          </button>
        </form>
      ) : (
        <>
          <dl className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            {[
              ["Open actions", "open_action_count"],
              ["Completed actions", "completed_action_count"],
              ["Alerts during shift", "alerts_during_shift_count"],
              ["Unresolved alerts", "unresolved_alert_count"],
              ["Critical machines", "critical_machine_count"],
            ].map(([label, key]) => (
              <div className={operationalPanelClassName} key={key}>
                <dt className="text-xs font-semibold uppercase text-muted-foreground">
                  {label}
                </dt>
                <dd className="mt-2 text-2xl font-semibold text-foreground">
                  {snapshotCount(shift.snapshot, key)}
                </dd>
              </div>
            ))}
          </dl>
          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <section className={operationalPanelClassName}>
              <h2 className="font-semibold text-foreground">Handover notes</h2>
              <p className="mt-2 whitespace-pre-wrap text-sm text-secondary-foreground">
                {shift.handover_notes || "No handover notes recorded."}
              </p>
            </section>
            <section className={operationalPanelClassName}>
              <h2 className="font-semibold text-foreground">Unresolved items</h2>
              <p className="mt-2 whitespace-pre-wrap text-sm text-secondary-foreground">
                {shift.unresolved_summary || "No unresolved items recorded."}
              </p>
            </section>
            {shift.status === "ended" ? (
              <button
                className={`${buttonClassName("primary")} print:hidden`}
                disabled={busy}
                onClick={acknowledge}
                type="button"
              >
                Acknowledge next-shift handover
              </button>
            ) : null}
          </div>
        </>
      )}
      {mutationError ? (
        <div className="mt-4 print:hidden">
          <OperationalError error={mutationError} />
        </div>
      ) : null}
    </section>
  );
}
