import { useEffect, useState, type ReactElement } from "react";
import { Link, useParams } from "react-router-dom";

import {
  acknowledgeMachineRisk,
  getMachineRisk,
  type MachineRisk,
} from "../../api/pilot";
import { isRequestCancelled } from "../../api/client";
import {
  Breadcrumbs,
  InlineError,
  LoadingSkeleton,
  primaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import {
  IntelligenceStatus,
  KeyValues,
  formatDate,
  panelClassName,
} from "../../components/intelligence/IntelligenceUi";
import { PageHeader } from "../../components/ui/PageHeader";

export function MachineRiskPage(): ReactElement {
  const { factoryId = "", machineId = "" } = useParams();
  const [risk, setRisk] = useState<MachineRisk | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [operatorNote, setOperatorNote] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getMachineRisk(machineId, controller.signal)
      .then((value) => {
        setRisk(value);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal))
          setError(
            caught instanceof Error ? caught.message : "Machine risk unavailable.",
          );
      });
    return () => controller.abort();
  }, [machineId, revision]);

  if (error)
    return (
      <InlineError
        message={error}
        onRetry={() => {
          setError(null);
          setRevision((value) => value + 1);
        }}
      />
    );
  if (!risk) return <LoadingSkeleton label="Loading machine risk" />;

  return (
    <section>
      <Breadcrumbs
        items={[
          { label: "Factories", to: "/factories" },
          { label: "Factory", to: `/factories/${factoryId}` },
          {
            label: "Machine",
            to: `/factories/${factoryId}/machines/${machineId}`,
          },
          { label: "Risk indication" },
        ]}
      />
      <PageHeader
        eyebrow="Predictive maintenance pilot"
        headingId="machine-risk-heading"
        title="Machine risk indication"
        description="A controlled anomaly-risk indication for operator review. It is not a guaranteed failure prediction or a maintenance work order."
        actions={
          risk.acknowledged_at ? (
            <IntelligenceStatus value="acknowledged" />
          ) : (
            <button
              className={primaryButtonClassName}
              disabled={busy}
              onClick={() => {
                setBusy(true);
                setActionError(null);
                void acknowledgeMachineRisk(risk.id, operatorNote)
                  .then(() => {
                    setOperatorNote("");
                    setRevision((value) => value + 1);
                  })
                  .catch((caught: unknown) =>
                    setActionError(
                      caught instanceof Error
                        ? caught.message
                        : "The indication could not be acknowledged.",
                    ),
                  )
                  .finally(() => setBusy(false));
              }}
              type="button"
            >
              {busy ? "Acknowledging…" : "Acknowledge indication"}
            </button>
          )
        }
      />
      {!risk.acknowledged_at ? (
        <div className={`${panelClassName} mt-6`}>
          <label
            className="block text-sm font-semibold text-foreground"
            htmlFor="operator-risk-note"
          >
            Operator note
          </label>
          <textarea
            className="mt-2 min-h-24 w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            id="operator-risk-note"
            maxLength={1000}
            onChange={(event) => setOperatorNote(event.target.value)}
            placeholder="Optional operational context for the acknowledgement"
            value={operatorNote}
          />
          {actionError ? (
            <p className="mt-2 text-sm text-destructive" role="alert">
              {actionError}
            </p>
          ) : null}
        </div>
      ) : null}
      <div className="mt-6">
        <KeyValues
          items={[
            {
              label: "Current state",
              value: <IntelligenceStatus value={risk.risk_state} />,
            },
            {
              label: "Risk score",
              value:
                risk.risk_score === null
                  ? "Unavailable"
                  : `${Math.round(risk.risk_score * 100)}%`,
            },
            { label: "Assessed", value: formatDate(risk.assessed_at) },
            {
              label: "Data freshness",
              value:
                risk.data_freshness_seconds === null
                  ? "Unavailable"
                  : `${Math.round(risk.data_freshness_seconds)} seconds`,
            },
            {
              label: "Model",
              value: `${risk.registered_model_name} / ${risk.model_version}`,
            },
            {
              label: "Monitoring",
              value: <IntelligenceStatus value={risk.monitoring_status} />,
            },
          ]}
        />
      </div>
      <section className={`${panelClassName} mt-6`}>
        <h3 className="text-lg font-semibold text-foreground">
          Recommended operator action
        </h3>
        <p className="mt-2 text-sm leading-6 text-secondary-foreground">
          {risk.recommended_action}
        </p>
      </section>
      <section className={`${panelClassName} mt-6`}>
        <h3 className="text-lg font-semibold text-foreground">
          Contributing sensor values
        </h3>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-muted text-muted-foreground">
              <tr>
                <th className="px-3 py-2">Feature</th>
                <th className="px-3 py-2">Value</th>
                <th className="px-3 py-2">Unit</th>
              </tr>
            </thead>
            <tbody>
              {risk.sensor_values.map((item, index) => (
                <tr
                  className="border-t border-border"
                  key={`${String(item.name)}-${index}`}
                >
                  <td className="px-3 py-2">{String(item.name ?? "Feature")}</td>
                  <td className="px-3 py-2">{String(item.value ?? "Unavailable")}</td>
                  <td className="px-3 py-2">{String(item.unit ?? "—")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <p className="mt-6 text-sm">
        <Link className="font-semibold text-link" to="/monitoring">
          Engineer monitoring drill-down
        </Link>
      </p>
    </section>
  );
}
