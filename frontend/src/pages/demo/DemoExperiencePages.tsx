import { useEffect, useMemo, useState, type FormEvent, type ReactElement } from "react";
import { Link, useParams } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import {
  advanceDemoRun,
  checkGuidedReadiness,
  confirmImport,
  controlDemoRun,
  createReport,
  downloadImportQuality,
  downloadReport,
  getDemoRun,
  getExecutiveDashboard,
  getFactoryLayout,
  getFactoryMapState,
  getReport,
  getTvSummary,
  listGuidedImports,
  listReports,
  resetDemoRun,
  saveFactoryLayout,
  saveImportMapping,
  startDemoRun,
  uploadGuidedCsv,
  validateImport,
  type DataImport,
  type DemoRun,
  type ExecutiveDashboard,
  type FactoryLayout,
  type FactoryMapState,
  type ReadinessResult,
  type ReportJob,
} from "../../api/demoExperience";
import {
  listFactories,
  listMachines,
  listSensors,
  type Factory,
  type Machine,
  type Sensor,
} from "../../api/hierarchy";
import { useAuth } from "../../auth/useAuth";
import { hasProductCapability } from "../../auth/permissions";
import {
  EmptyState,
  InlineError,
  InlineNotice,
  LoadingSkeleton,
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { PageHeader } from "../../components/ui/PageHeader";

const panel = "rounded-lg border border-border bg-card p-5 shadow-panel";
const input =
  "w-full rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function message(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

export function DataOnboardingPage(): ReactElement {
  const [item, setItem] = useState<DataImport | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [recognizedAssets, setRecognizedAssets] = useState<
    readonly {
      readonly machine: Machine;
      readonly sensors: readonly Sensor[];
    }[]
  >([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const headers = useMemo(
    () => (item?.preview[0] === undefined ? [] : Object.keys(item.preview[0])),
    [item],
  );
  const guessed = (name: string): string =>
    headers.find((header) => header.toLowerCase().includes(name)) ?? "";
  const hasBlockingIssues =
    item?.quality_report.issues instanceof Array &&
    item.quality_report.issues.some(
      (issue) =>
        typeof issue === "object" &&
        issue !== null &&
        (issue as Record<string, unknown>).severity === "Blocking",
    );

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    void listFactories({ limit: 20, signal: controller.signal })
      .then(async (factories) => {
        const machinePages = await Promise.all(
          factories.items.map((factory) =>
            listMachines(factory.id, { limit: 100, signal: controller.signal }),
          ),
        );
        const machines = machinePages.flatMap((page) => [...page.items]);
        const sensorPages = await Promise.all(
          machines.map((machine) =>
            listSensors(machine.id, { limit: 100, signal: controller.signal }),
          ),
        );
        if (active) {
          setRecognizedAssets(
            machines.map((machine, index) => ({
              machine,
              sensors: sensorPages[index]?.items ?? [],
            })),
          );
        }
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal)) {
          setRecognizedAssets([]);
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  const execute = async (operation: () => Promise<DataImport>): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      setItem(await operation());
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="onboarding-heading">
      <PageHeader
        description="Upload a CSV of machine readings, match its columns, review any data issues, and confirm what should be imported."
        eyebrow="Machine data"
        headingId="onboarding-heading"
        title="Data Onboarding"
      />
      <ol className="mt-6 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {["Upload", "Preview", "Map columns", "Validate", "Confirm", "Result"].map(
          (step, index) => (
            <li className={`${panel} py-3 text-sm`} key={step}>
              <span className="mr-2 font-mono text-eyebrow">{index + 1}</span>
              {step}
            </li>
          ),
        )}
      </ol>
      <InlineNotice>
        Choosing a file does not import it. You can preview the rows, match each column,
        and correct blocking issues before confirming the import.
      </InlineNotice>
      <div className={`${panel} mt-4`}>
        <h3 className="font-semibold text-foreground">How to format your CSV</h3>
        <p className="mt-2 text-sm text-secondary-foreground">
          Map columns containing timestamp, machine name, sensor name, and numeric
          value. Names must match registered resources exactly.
        </p>
        <pre className="mt-3 overflow-x-auto rounded-md bg-muted p-3 text-xs text-foreground">
          timestamp,machine,sensor,value,unit{"\n"}
          2026-07-25T08:00:00Z,CNC-01,temperature_c,61.2,°C
        </pre>
        <div className="mt-3">
          <p className="text-sm font-medium text-foreground">
            Recognized machines and sensors
          </p>
          {recognizedAssets.length === 0 ? (
            <p className="mt-1 text-sm text-secondary-foreground">
              No registered assets are available yet.{" "}
              <Link className="font-semibold text-link hover:underline" to="/factories">
                Open factory assets
              </Link>
              .
            </p>
          ) : (
            <ul className="mt-2 grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
              {recognizedAssets.map(({ machine, sensors }) => (
                <li
                  className="rounded-md border border-border bg-elevated p-3"
                  key={machine.id}
                >
                  <strong className="text-foreground">{machine.name}</strong>
                  <p className="mt-1 text-xs text-secondary-foreground">
                    {sensors.map((sensor) => sensor.name).join(", ") ||
                      "No sensors registered"}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      {error ? (
        <div className="mt-4">
          <InlineError message={error} onRetry={() => setError(null)} />
        </div>
      ) : null}
      <div className="mt-6 grid gap-5 lg:grid-cols-2">
        <div className={panel}>
          <h3 className="font-semibold text-foreground">1. Upload CSV</h3>
          <input
            accept=".csv,text/csv"
            aria-label="CSV file"
            className={`${input} mt-4`}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            type="file"
          />
          <button
            className={`mt-4 ${primaryButtonClassName}`}
            disabled={busy || file === null}
            onClick={() => {
              if (file)
                void execute(() =>
                  uploadGuidedCsv(file, `browser-${crypto.randomUUID()}`),
                );
            }}
            type="button"
          >
            {busy ? "Uploading…" : "Upload for preview"}
          </button>
        </div>
        <div className={panel}>
          <h3 className="font-semibold text-foreground">2. Bounded preview</h3>
          {item === null ? (
            <p className="mt-3 text-sm text-secondary-foreground">
              Select a CSV to inspect its detected delimiter, headers, and first rows.
            </p>
          ) : (
            <>
              <p className="mt-2 text-sm text-secondary-foreground">
                {item.filename} · {item.total_rows} rows · delimiter “{item.delimiter}”
              </p>
              <div className="mt-3 overflow-auto">
                <table className="min-w-full text-left text-xs">
                  <thead>
                    <tr>
                      {headers.map((header) => (
                        <th className="bg-muted px-2 py-2" key={header}>
                          {header}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {item.preview.slice(0, 5).map((row, index) => (
                      <tr key={index}>
                        {headers.map((header) => (
                          <td className="border-t border-border px-2 py-2" key={header}>
                            {String(row[header] ?? "")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
        <div className={panel}>
          <h3 className="font-semibold text-foreground">3. Confirm mapping</h3>
          <p className="mt-2 text-sm text-secondary-foreground">
            Suggestions are not applied until you confirm. This quick mapping supports
            the common long shape: timestamp, machine, sensor, value.
          </p>
          <form
            className="mt-4 grid gap-3 sm:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (item === null) return;
              const data = new FormData(event.currentTarget);
              void execute(() =>
                saveImportMapping(item.id, {
                  machine: String(data.get("machine")),
                  sensor: String(data.get("sensor")),
                  shape: "long",
                  timestamp: String(data.get("timestamp")),
                  value: String(data.get("value")),
                }),
              );
            }}
          >
            {(["timestamp", "machine", "sensor", "value"] as const).map((field) => (
              <label className="text-sm font-medium text-foreground" key={field}>
                {field[0].toUpperCase() + field.slice(1)}
                <select
                  className={`${input} mt-1`}
                  defaultValue={guessed(field === "timestamp" ? "time" : field)}
                  disabled={busy || item === null}
                  key={`${item?.id ?? "empty"}-${field}`}
                  name={field}
                  required
                >
                  <option value="">Select a column</option>
                  {headers.map((header) => (
                    <option key={header} value={header}>
                      {header}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            <button
              className={`${secondaryButtonClassName} sm:col-span-2`}
              disabled={busy || item === null}
              type="submit"
            >
              Confirm column mapping
            </button>
          </form>
        </div>
        <div className={panel}>
          <h3 className="font-semibold text-foreground">4. Quality report</h3>
          <button
            className={`mt-4 ${secondaryButtonClassName}`}
            disabled={busy || item === null || !("confirmed" in item.mapping)}
            onClick={() => {
              if (item) void execute(() => validateImport(item.id));
            }}
            type="button"
          >
            Validate data
          </button>
          {item?.quality_report.issues instanceof Array ? (
            <ul className="mt-4 space-y-2 text-sm">
              {item.quality_report.issues.map((issue, index) => (
                <li className="rounded-md bg-muted p-3" key={index}>
                  <strong>
                    {String((issue as Record<string, unknown>).severity)} ·{" "}
                    {String((issue as Record<string, unknown>).code)}
                  </strong>
                  <p className="mt-1 text-secondary-foreground">
                    {String((issue as Record<string, unknown>).meaning)}{" "}
                    {String((issue as Record<string, unknown>).correction)}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Count: {String((issue as Record<string, unknown>).count)}
                  </p>
                </li>
              ))}
            </ul>
          ) : null}
          {item?.quality_report.issues instanceof Array ? (
            <button
              className={`mt-3 ${secondaryButtonClassName}`}
              onClick={() => {
                void downloadImportQuality(item.id).then((blob) => {
                  const url = URL.createObjectURL(blob);
                  const anchor = document.createElement("a");
                  anchor.href = url;
                  anchor.download = `quality-${item.id}.csv`;
                  anchor.click();
                  URL.revokeObjectURL(url);
                });
              }}
              type="button"
            >
              Download quality issue summary
            </button>
          ) : null}
          {item?.error_samples.length ? (
            <details className="mt-3 text-sm">
              <summary className="cursor-pointer font-semibold text-link">
                Review bounded row examples
              </summary>
              <ul className="mt-2 space-y-2">
                {item.error_samples.map((sample, index) => (
                  <li className="rounded-md border border-border p-2" key={index}>
                    Row {String(sample.row)} · {String(sample.code)} ·{" "}
                    {String(sample.detail)}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
        <div className={panel}>
          <h3 className="font-semibold text-foreground">5. Confirm import</h3>
          <p className="mt-2 text-sm text-secondary-foreground">
            Blocking issues prevent import. Warnings are accepted explicitly; no rows
            are silently deleted.
          </p>
          <button
            className={`mt-4 ${primaryButtonClassName}`}
            disabled={
              busy ||
              item === null ||
              !("issues" in item.quality_report) ||
              hasBlockingIssues
            }
            onClick={() => {
              if (item) void execute(() => confirmImport(item.id, true));
            }}
            type="button"
          >
            Confirm and import
          </button>
        </div>
        <div className={panel} aria-live="polite">
          <h3 className="font-semibold text-foreground">6. Import result</h3>
          <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
            <dt>Status</dt>
            <dd>{item?.status ?? "Not started"}</dd>
            <dt>Imported</dt>
            <dd>{item?.imported_rows ?? 0}</dd>
            <dt>Rejected</dt>
            <dd>{item?.rejected_rows ?? 0}</dd>
            <dt>Progress</dt>
            <dd>{item?.progress_percent ?? 0}%</dd>
          </dl>
          {item?.completed_at !== null && item?.completed_at !== undefined ? (
            <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4">
              <Link className={secondaryButtonClassName} to="/sensor-data/quality">
                Review data quality
              </Link>
              <Link className={primaryButtonClassName} to="/guided-ai">
                Continue to Guided AI
              </Link>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

export function DataQualityPage(): ReactElement {
  const { role } = useAuth();
  const canWrite = hasProductCapability(role, "engineering.write");
  const [items, setItems] = useState<readonly DataImport[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    listGuidedImports(controller.signal)
      .then((page) => setItems(page.items))
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal)) setError(message(caught));
      });
    return () => controller.abort();
  }, []);
  return (
    <section aria-labelledby="quality-heading">
      <PageHeader
        actions={
          canWrite ? (
            <Link className={primaryButtonClassName} to="/sensor-data/onboarding">
              Start a data import
            </Link>
          ) : undefined
        }
        description="Review recent imports, rejected rows, and issues that must be corrected before the data can be trusted."
        eyebrow="Machine data"
        headingId="quality-heading"
        title="Data quality"
      />
      <div className="mt-6">
        {error ? (
          <InlineError message={error} onRetry={() => location.reload()} />
        ) : items === null ? (
          <LoadingSkeleton />
        ) : items.length === 0 ? (
          <EmptyState
            description={
              canWrite
                ? "Start a data import to establish quality history."
                : "No data-quality history is available to review yet."
            }
            title="No quality history"
          />
        ) : (
          <div className="grid gap-4">
            {items.map((item) => {
              const invalid = Number(item.quality_report.invalid_rows ?? 0);
              const rate = item.total_rows ? (invalid / item.total_rows) * 100 : 0;
              return (
                <article className={panel} key={item.id}>
                  <div className="flex flex-wrap justify-between gap-3">
                    <div>
                      <h3 className="font-semibold">{item.filename}</h3>
                      <p className="text-sm text-secondary-foreground">
                        {item.status} · {new Date(item.created_at).toLocaleString()}
                      </p>
                    </div>
                    <strong>
                      {invalid} invalid · {rate.toFixed(1)}%
                    </strong>
                  </div>
                  {item.quality_report.issues instanceof Array ? (
                    <ul className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                      {item.quality_report.issues.map((issue, index) => (
                        <li className="rounded-md bg-muted p-3" key={index}>
                          <strong>
                            {String((issue as Record<string, unknown>).severity)} ·{" "}
                            {String((issue as Record<string, unknown>).code)}
                          </strong>
                          <p className="mt-1 text-secondary-foreground">
                            {String((issue as Record<string, unknown>).meaning)}
                          </p>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </article>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

export function GuidedAiPage(): ReactElement {
  const [imports, setImports] = useState<readonly DataImport[]>([]);
  const [result, setResult] = useState<ReadinessResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void listGuidedImports()
      .then((page) => setImports(page.items))
      .catch((caught: unknown) => setError(message(caught)));
  }, []);
  const submit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const importId = String(data.get("import"));
    const features = String(data.get("features"))
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    void checkGuidedReadiness({
      features,
      import_id: importId,
      profile: String(data.get("profile")) as "balanced",
      target: String(data.get("target") || "") || undefined,
      use_case: String(data.get("use_case")) as "condition_monitoring",
    })
      .then(setResult)
      .catch((caught: unknown) => setError(message(caught)));
  };
  return (
    <section aria-labelledby="guided-ai-heading">
      <PageHeader
        description="Choose a factory goal and a completed data import. FactoryMind checks whether the data is ready before model training begins."
        eyebrow="Guided AI"
        headingId="guided-ai-heading"
        title="Prepare an AI use case"
      />
      {error ? <InlineError message={error} onRetry={() => setError(null)} /> : null}
      {imports.length === 0 ? (
        <div className="mt-5">
          <InlineNotice>
            Complete a machine-data import before checking an AI use case.{" "}
            <Link className="font-semibold text-link" to="/sensor-data/onboarding">
              Open Data Onboarding
            </Link>
            .
          </InlineNotice>
        </div>
      ) : null}
      <form className={`mt-6 grid gap-4 ${panel}`} onSubmit={submit}>
        <label>
          <span className="text-sm font-medium">Use case</span>
          <select className={`${input} mt-1`} name="use_case">
            <option value="predictive_maintenance">Predictive maintenance</option>
            <option value="energy_monitoring">Energy monitoring</option>
            <option value="quality_prediction">Quality prediction</option>
            <option value="condition_monitoring">Condition monitoring</option>
          </select>
        </label>
        <label>
          <span className="text-sm font-medium">Completed machine-data import</span>
          <select className={`${input} mt-1`} name="import" required>
            <option value="">Select an import</option>
            {imports.map((item) => (
              <option key={item.id} value={item.id}>
                {item.filename} · {item.status}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="text-sm font-medium">Data columns to use</span>
          <input className={`${input} mt-1`} name="features" required />
          <span className="mt-1 block text-xs text-muted-foreground">
            Enter the useful measurement columns, separated by commas.
          </span>
        </label>
        <label>
          <span className="text-sm font-medium">Value to predict (optional)</span>
          <input className={`${input} mt-1`} name="target" />
        </label>
        <label>
          <span className="text-sm font-medium">Analysis depth</span>
          <select className={`${input} mt-1`} name="profile">
            <option value="fast_demo">Quick check</option>
            <option value="balanced">Balanced</option>
            <option value="thorough">Thorough</option>
          </select>
        </label>
        <button className={primaryButtonClassName} type="submit">
          Check readiness
        </button>
      </form>
      {result ? (
        <article className={`mt-5 ${panel}`} aria-live="polite">
          <h3 className="font-semibold">
            {result.ready ? "Ready to begin model training" : "More preparation needed"}
          </h3>
          <p className="mt-2 text-sm">
            {result.valid_rows}/{result.dataset_size} valid rows ·{" "}
            {(result.missingness_rate * 100).toFixed(1)}% missing/invalid
          </p>
          <p className="mt-2 text-sm">{result.profile_summary}</p>
          <p className="mt-2 text-sm">{result.deployment_consequence}</p>
          {result.blocking_issues.length ? (
            <ul className="mt-3 list-disc pl-5 text-sm">
              {result.blocking_issues.map((issue) => (
                <li key={issue}>{issue.replaceAll("_", " ")}</li>
              ))}
            </ul>
          ) : null}
          {result.ready ? (
            <Link
              className={`mt-4 inline-flex ${primaryButtonClassName}`}
              to="/training"
            >
              Continue to training
            </Link>
          ) : null}
        </article>
      ) : null}
    </section>
  );
}

export function DemoControlPage(): ReactElement {
  const [factories, setFactories] = useState<readonly Factory[]>([]);
  const [machines, setMachines] = useState<readonly Machine[]>([]);
  const [factoryId, setFactoryId] = useState("");
  const [machineId, setMachineId] = useState("");
  const [scenario, setScenario] = useState("normal_operation");
  const [run, setRun] = useState<DemoRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const tourSteps = [
    "Factory overview",
    "Live machine",
    "Risk change",
    "Alert creation",
    "Required action",
    "Operator completion",
    "Recovery",
    "Executive summary",
  ] as const;
  const [tourStep, setTourStep] = useState<number | null>(() =>
    localStorage.getItem("fk-demo-tour-complete") === "true" ? null : 0,
  );
  const runId = run?.id ?? null;
  const runStatus = run?.status ?? null;
  useEffect(() => {
    void listFactories({ limit: 100 }).then((page) => setFactories(page.items));
  }, []);
  useEffect(() => {
    if (!factoryId) return;
    void listMachines(factoryId).then((page) => setMachines(page.items));
  }, [factoryId]);
  useEffect(() => {
    if (!runId || !runStatus || !["running", "paused"].includes(runStatus)) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      void getDemoRun(runId, controller.signal)
        .then(setRun)
        .catch((caught: unknown) => {
          if (!isRequestCancelled(caught, controller.signal)) setError(message(caught));
        });
    }, 3000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [runId, runStatus]);
  const action = async (operation: () => Promise<DemoRun>): Promise<void> => {
    if (busy) return;
    setBusy(true);
    try {
      setRun(await operation());
      setError(null);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section aria-labelledby="demo-control-heading">
      <PageHeader
        description="Explicitly advance one deterministic scenario step at a time. The simulator has no infinite background loop."
        eyebrow="Live demonstration"
        headingId="demo-control-heading"
        title="Demo Control Center"
      />
      {tourStep !== null ? (
        <aside className={`mt-5 ${panel}`} aria-label="Guided demo tour">
          <p className="text-xs font-semibold uppercase tracking-wide text-eyebrow">
            Tour {tourStep + 1} of {tourSteps.length}
          </p>
          <h3 className="mt-2 font-semibold">{tourSteps[tourStep]}</h3>
          <p className="mt-2 text-sm text-secondary-foreground">
            Follow the deterministic scenario from factory context through recovery and
            the grounded executive summary.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              className={secondaryButtonClassName}
              onClick={() => setTourStep(null)}
              type="button"
            >
              Skip
            </button>
            <button
              className={primaryButtonClassName}
              onClick={() => {
                if (tourStep === tourSteps.length - 1) {
                  localStorage.setItem("fk-demo-tour-complete", "true");
                  setTourStep(null);
                } else {
                  setTourStep(tourStep + 1);
                }
              }}
              type="button"
            >
              {tourStep === tourSteps.length - 1 ? "Finish" : "Next"}
            </button>
          </div>
        </aside>
      ) : (
        <button
          className={`mt-4 ${secondaryButtonClassName}`}
          onClick={() => {
            localStorage.removeItem("fk-demo-tour-complete");
            setTourStep(0);
          }}
          type="button"
        >
          Restart guided tour
        </button>
      )}
      {error ? <InlineError message={error} onRetry={() => setError(null)} /> : null}
      <div className={`mt-6 grid gap-4 md:grid-cols-2 ${panel}`}>
        <select
          aria-label="Demo factory"
          className={input}
          onChange={(event) => setFactoryId(event.target.value)}
        >
          <option value="">Select factory</option>
          {factories.map((factory) => (
            <option key={factory.id} value={factory.id}>
              {factory.name}
            </option>
          ))}
        </select>
        <select
          aria-label="Demo machine"
          className={input}
          onChange={(event) => setMachineId(event.target.value)}
        >
          <option value="">Select machine</option>
          {machines.map((machine) => (
            <option key={machine.id} value={machine.id}>
              {machine.name}
            </option>
          ))}
        </select>
        <select
          aria-label="Demo scenario"
          className={input}
          onChange={(event) => setScenario(event.target.value)}
          value={scenario}
        >
          {[
            "normal_operation",
            "gradual_degradation",
            "warning_threshold",
            "critical_condition",
            "sensor_fault",
            "data_dropout",
            "maintenance_intervention",
            "recovery_to_normal",
          ].map((value) => (
            <option key={value} value={value}>
              {value.replaceAll("_", " ")}
            </option>
          ))}
        </select>
        <button
          className={primaryButtonClassName}
          disabled={busy || !factoryId || !machineId}
          onClick={() =>
            void action(() =>
              startDemoRun({
                factory_id: factoryId,
                idempotency_key: `browser-${crypto.randomUUID()}`,
                machine_id: machineId,
                scenario,
                speed: 1,
              }),
            )
          }
          type="button"
        >
          Start scenario
        </button>
      </div>
      {run ? (
        <article className={`mt-5 ${panel}`} aria-live="polite">
          <h3 className="font-semibold">{run.scenario.replaceAll("_", " ")}</h3>
          <p className="mt-2 text-sm">
            {run.status} · step {run.current_step} · {run.generated_readings} readings
          </p>
          <p className="mt-2 text-sm">
            Risk: {String(run.state_snapshot.risk_state ?? "unknown")} · Next:{" "}
            {String(run.state_snapshot.expected_next_event ?? "unknown")}
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              className={primaryButtonClassName}
              disabled={busy || run.status !== "running"}
              onClick={() => void action(() => advanceDemoRun(run.id))}
              type="button"
            >
              Advance
            </button>
            {run.status === "running" ? (
              <button
                className={secondaryButtonClassName}
                disabled={busy}
                onClick={() => void action(() => controlDemoRun(run.id, "pause"))}
                type="button"
              >
                Pause
              </button>
            ) : run.status === "paused" ? (
              <button
                className={secondaryButtonClassName}
                disabled={busy}
                onClick={() => void action(() => controlDemoRun(run.id, "resume"))}
                type="button"
              >
                Resume
              </button>
            ) : null}
            <button
              className={secondaryButtonClassName}
              disabled={busy}
              onClick={() => void action(() => controlDemoRun(run.id, "stop"))}
              type="button"
            >
              Stop
            </button>
            <button
              className={secondaryButtonClassName}
              disabled={busy}
              onClick={() => {
                if (window.confirm("Reset only records generated by this demo run?"))
                  void (async () => {
                    setBusy(true);
                    try {
                      await resetDemoRun(run.id);
                      setRun(null);
                    } catch (caught) {
                      setError(message(caught));
                    } finally {
                      setBusy(false);
                    }
                  })();
              }}
              type="button"
            >
              Reset demo records
            </button>
          </div>
        </article>
      ) : null}
    </section>
  );
}

export function FactoryMapPage(): ReactElement {
  const { factoryId = "" } = useParams();
  const { role } = useAuth();
  const [machines, setMachines] = useState<readonly Machine[]>([]);
  const [layout, setLayout] = useState<FactoryLayout | null>(null);
  const [states, setStates] = useState<readonly FactoryMapState[]>([]);
  const [filter, setFilter] = useState("all");
  const [zoom, setZoom] = useState(1);
  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      listMachines(factoryId, { signal: controller.signal }),
      getFactoryLayout(factoryId, controller.signal),
      getFactoryMapState(factoryId, controller.signal),
    ]).then(([page, value, stateValues]) => {
      setMachines(page.items);
      setLayout(value);
      setStates(stateValues);
    });
    return () => controller.abort();
  }, [factoryId]);
  const nodes =
    layout?.nodes ??
    machines.map((machine, index) => ({
      machine_id: machine.id,
      x: 15 + (index % 4) * 22,
      y: 20 + Math.floor(index / 4) * 30,
    }));
  const visibleNodes = nodes.filter((node) => {
    if (filter === "all") return true;
    return (
      states.find((value) => value.machine_id === node.machine_id)?.state === filter
    );
  });
  return (
    <section aria-labelledby="factory-map-heading">
      <PageHeader
        actions={
          <Link className={secondaryButtonClassName} to={`/factories/${factoryId}/tv`}>
            Open TV mode
          </Link>
        }
        description="A simple keyboard-accessible 2D layout of existing machines. Positions do not infer physical coordinates."
        eyebrow="Factory visualization"
        headingId="factory-map-heading"
        title="Factory map"
      />
      <div className="mt-5 flex flex-wrap gap-2">
        <select
          aria-label="Filter machines by state"
          className={input}
          onChange={(event) => setFilter(event.target.value)}
          value={filter}
        >
          <option value="all">All states</option>
          {["normal", "observe", "warning", "critical", "insufficient_data"].map(
            (value) => (
              <option key={value} value={value}>
                {value.replaceAll("_", " ")}
              </option>
            ),
          )}
        </select>
        <button
          className={secondaryButtonClassName}
          onClick={() => setZoom((value) => Math.min(1.5, value + 0.1))}
          type="button"
        >
          Zoom in
        </button>
        <button
          className={secondaryButtonClassName}
          onClick={() => setZoom(1)}
          type="button"
        >
          Fit
        </button>
        <button
          className={secondaryButtonClassName}
          onClick={() =>
            void document.getElementById("factory-map-canvas")?.requestFullscreen()
          }
          type="button"
        >
          Fullscreen
        </button>
      </div>
      <div
        className={`relative mt-4 min-h-[420px] overflow-hidden ${panel}`}
        id="factory-map-canvas"
      >
        {visibleNodes.map((node) => {
          const machine = machines.find((value) => value.id === node.machine_id);
          const state = states.find((value) => value.machine_id === node.machine_id);
          return (
            <Link
              className="absolute w-36 rounded-md border border-purple-300 bg-card p-3 text-sm shadow-panel focus-visible:ring-2 focus-visible:ring-ring"
              key={node.machine_id}
              style={{
                left: `${node.x}%`,
                top: `${node.y}%`,
                transform: `scale(${zoom})`,
              }}
              to={`/factories/${factoryId}/machines/${node.machine_id}`}
            >
              <strong>{machine?.name ?? "Machine"}</strong>
              <span className="mt-1 block text-xs text-secondary-foreground">
                {state?.state.replaceAll("_", " ") ?? "insufficient data"} ·{" "}
                {state?.alert_count ?? 0} alerts · {state?.action_count ?? 0} actions
              </span>
            </Link>
          );
        })}
      </div>
      {role !== "operator" && layout === null && nodes.length ? (
        <button
          className={`mt-4 ${primaryButtonClassName}`}
          onClick={() => void saveFactoryLayout(factoryId, nodes).then(setLayout)}
          type="button"
        >
          Save suggested layout
        </button>
      ) : null}
      <ul className="mt-5 grid gap-2 sm:grid-cols-2" aria-label="Machine list fallback">
        {machines.map((machine) => (
          <li className={panel} key={machine.id}>
            <Link to={`/factories/${factoryId}/machines/${machine.id}`}>
              {machine.name}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function TvModePage(): ReactElement {
  const { factoryId = "" } = useParams();
  const [summary, setSummary] = useState<Readonly<Record<string, unknown>> | null>(
    null,
  );
  const [connected, setConnected] = useState(true);
  useEffect(() => {
    let active = true;
    const load = (): void => {
      void getTvSummary(factoryId)
        .then((value) => {
          if (active) {
            setSummary(value);
            setConnected(true);
          }
        })
        .catch(() => active && setConnected(false));
    };
    load();
    const timer = window.setInterval(load, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [factoryId]);
  if (!summary) return <LoadingSkeleton label="Loading TV mode" />;
  return (
    <section aria-labelledby="tv-heading">
      <PageHeader
        description={`Authenticated read-only display · ${connected ? "Connected" : "Disconnected"}`}
        eyebrow="TV mode"
        headingId="tv-heading"
        title={String(summary.factory_name)}
      />
      <div className="mt-8 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Overall state", summary.overall_state],
          ["Machines", summary.machine_count],
          ["Active alerts", summary.active_alerts],
          ["Urgent actions", summary.urgent_actions],
        ].map(([label, value]) => (
          <article className={`${panel} p-8`} key={String(label)}>
            <p className="text-sm text-secondary-foreground">{String(label)}</p>
            <strong className="mt-3 block text-3xl">{String(value)}</strong>
          </article>
        ))}
      </div>
      <p className="mt-6 text-sm text-secondary-foreground">
        Last update: {new Date(String(summary.last_update)).toLocaleString()}
      </p>
    </section>
  );
}

export function ExecutiveDashboardPage(): ReactElement {
  const [data, setData] = useState<ExecutiveDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getExecutiveDashboard(controller.signal)
      .then(setData)
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal)) setError(message(caught));
      });
    return () => controller.abort();
  }, []);
  return (
    <section aria-labelledby="executive-heading">
      <PageHeader
        actions={
          <Link className={primaryButtonClassName} to="/reports">
            Generate report
          </Link>
        }
        description="Grounded company metrics from authorized operational records. Each metric links back to its source workflow."
        eyebrow="Executive reporting"
        headingId="executive-heading"
        title="Executive dashboard"
      />
      {error ? (
        <InlineError message={error} onRetry={() => location.reload()} />
      ) : data === null ? (
        <LoadingSkeleton />
      ) : (
        <>
          <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Object.entries(data.metrics).map(([key, value]) => (
              <article className={panel} key={key}>
                <p className="text-sm text-secondary-foreground">
                  {key.replaceAll("_", " ")}
                </p>
                <strong className="mt-2 block text-2xl">
                  {String(value ?? "No data")}
                </strong>
                <p className="mt-2 text-xs text-secondary-foreground">
                  {data.definitions[key] ?? data.source}
                </p>
                {data.drill_downs[key] ? (
                  <Link
                    className="mt-3 inline-block text-sm font-semibold text-purple-700"
                    to={data.drill_downs[key]}
                  >
                    Drill down
                  </Link>
                ) : null}
              </article>
            ))}
          </div>
          <div className="mt-5">
            <InlineNotice>{data.limitations}</InlineNotice>
          </div>
        </>
      )}
    </section>
  );
}

export function ReportsPage(): ReactElement {
  const [reports, setReports] = useState<readonly ReportJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const load = (): void => {
    void listReports()
      .then(setReports)
      .catch((caught: unknown) => setError(message(caught)));
  };
  useEffect(load, []);
  const generate = (format: "csv" | "pdf" | "xlsx"): void => {
    const end = new Date();
    const start = new Date(end.getTime() - 7 * 86_400_000);
    void createReport({
      format,
      idempotency_key: `browser-${crypto.randomUUID()}`,
      period_end: end.toISOString(),
      period_start: start.toISOString(),
      report_type: "executive_factory_summary",
    })
      .then(load)
      .catch((caught: unknown) => setError(message(caught)));
  };
  return (
    <section aria-labelledby="reports-heading">
      <PageHeader
        description="Generate bounded, company-scoped exports. Downloads expire after one hour and require an authenticated session."
        eyebrow="Executive reporting"
        headingId="reports-heading"
        title="Reports"
      />
      {error ? <InlineError message={error} onRetry={() => setError(null)} /> : null}
      <div className="mt-6 flex flex-wrap gap-2">
        {(["pdf", "xlsx", "csv"] as const).map((format) => (
          <button
            className={primaryButtonClassName}
            key={format}
            onClick={() => generate(format)}
            type="button"
          >
            Generate {format.toUpperCase()}
          </button>
        ))}
      </div>
      <div className="mt-6 grid gap-4">
        {reports.map((report) => (
          <article className={panel} key={report.id}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-semibold">
                  {report.report_type.replaceAll("_", " ")}
                </h3>
                <p className="text-sm text-secondary-foreground">
                  {report.format.toUpperCase()} · {report.status} ·{" "}
                  {new Date(report.created_at).toLocaleString()}
                </p>
              </div>
              <Link className={secondaryButtonClassName} to={`/reports/${report.id}`}>
                Open
              </Link>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export function ReportDetailPage(): ReactElement {
  const { reportId = "" } = useParams();
  const [report, setReport] = useState<ReportJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getReport(reportId, controller.signal)
      .then(setReport)
      .catch((caught: unknown) => setError(message(caught)));
    return () => controller.abort();
  }, [reportId]);
  if (error) return <InlineError message={error} onRetry={() => setError(null)} />;
  if (!report) return <LoadingSkeleton label="Loading report" />;
  return (
    <section aria-labelledby="report-detail-heading">
      <PageHeader
        actions={
          <button
            className={primaryButtonClassName}
            onClick={() =>
              void downloadReport(report.id).then((blob) => {
                const url = URL.createObjectURL(blob);
                const anchor = document.createElement("a");
                anchor.href = url;
                anchor.download = `${report.report_type}.${report.format}`;
                anchor.click();
                URL.revokeObjectURL(url);
              })
            }
            type="button"
          >
            Download {report.format.toUpperCase()}
          </button>
        }
        description="Authorized generated report metadata and the grounded metric snapshot used for export."
        eyebrow="Report detail"
        headingId="report-detail-heading"
        title={report.report_type.replaceAll("_", " ")}
      />
      <dl className={`mt-6 grid gap-4 sm:grid-cols-2 ${panel}`}>
        {Object.entries(report.summary).map(([key, value]) => (
          <div key={key}>
            <dt className="text-sm text-secondary-foreground">
              {key.replaceAll("_", " ")}
            </dt>
            <dd className="mt-1 font-semibold">{String(value ?? "No data")}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-5">
        <InlineNotice>
          Downloads expire at{" "}
          {report.expires_at
            ? new Date(report.expires_at).toLocaleString()
            : "completion"}
          . Scheduled email delivery remains disabled when no mail provider is
          configured.
        </InlineNotice>
      </div>
    </section>
  );
}
