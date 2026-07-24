import { useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import {
  listAlgorithms,
  listTrainingJobs,
  type Algorithm,
  type TrainingTask,
} from "../../api/aiLifecycle";
import {
  executePrediction,
  executeStructuredPrediction,
  getFeatureSchema,
  listPredictionEvents,
  type PredictionEvent,
  type PredictionResponse,
  type ModelFeatureSchema,
} from "../../api/predictions";
import { useAuth } from "../../auth/useAuth";
import { ApiError, isRequestCancelled } from "../../api/client";
import {
  InlineNotice,
  primaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import {
  IntelligenceStatus,
  inputClassName,
  panelClassName,
} from "../../components/intelligence/IntelligenceUi";
import { PageHeader } from "../../components/ui/PageHeader";

function parseMatrix(value: string): number[][] {
  const parsed: unknown = JSON.parse(value);
  if (!Array.isArray(parsed) || parsed.length === 0 || !parsed.every(Array.isArray))
    throw new Error("Enter a non-empty JSON matrix.");
  const matrix = parsed as unknown[][];
  const width = matrix[0].length;
  if (width === 0 || matrix.some((row) => row.length !== width))
    throw new Error("Every feature row must have the same non-zero width.");
  if (
    matrix.some((row) =>
      row.some((item) => typeof item !== "number" || !Number.isFinite(item)),
    )
  )
    throw new Error("Every feature value must be a finite number.");
  return matrix as number[][];
}

function executionErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError))
    return error instanceof Error ? error.message : "Prediction execution failed.";
  if (error.status === 422)
    return error.message || "The feature matrix is invalid for the selected model.";
  if (error.status === 409)
    return `The prediction request conflicts with the selected model. ${error.message}`;
  if (error.status === 502 || error.status === 503)
    return "The model service is temporarily unavailable. Please try again later.";
  if (error.status === 500)
    return "Prediction execution failed. Please verify the inputs or try again later.";
  return error.message;
}

export function PredictionsPage(): ReactElement {
  const { role } = useAuth();
  const canReadHistory = role === "admin" || role === "engineer";
  const [model, setModel] = useState("");
  const [version, setVersion] = useState("");
  const [task, setTask] = useState<TrainingTask>("regression");
  const [algorithm, setAlgorithm] = useState("");
  const [algorithms, setAlgorithms] = useState<readonly Algorithm[]>([]);
  const [matrix, setMatrix] = useState("[[0.75, 1.4]]");
  const [executionResult, setExecutionResult] = useState<PredictionResponse | null>(
    null,
  );
  const [events, setEvents] = useState<readonly PredictionEvent[]>([]);
  const [executionError, setExecutionError] = useState<string | null>(null);
  const [executionLoading, setExecutionLoading] = useState(false);
  const [featureMatrixInvalid, setFeatureMatrixInvalid] = useState(false);
  const [loadWarning, setLoadWarning] = useState<string | null>(null);
  const [featureSchema, setFeatureSchema] = useState<ModelFeatureSchema | null>(null);
  const [schemaUnavailable, setSchemaUnavailable] = useState(false);
  const [structuredValues, setStructuredValues] = useState<Record<string, string>>({});
  const [advancedInput, setAdvancedInput] = useState(false);
  const canUseAdvancedInput = role === "admin" || role === "engineer";

  useEffect(() => {
    if (!canReadHistory) return;
    const controller = new AbortController();
    let active = true;
    Promise.allSettled([
      listTrainingJobs({
        limit: 100,
        offset: 0,
        signal: controller.signal,
        status: "succeeded",
      }),
      listPredictionEvents({ limit: 5, offset: 0, signal: controller.signal }),
      listAlgorithms(controller.signal),
    ]).then(([jobsResult, eventsResult, algorithmsResult]) => {
      if (!active) return;
      const failures: string[] = [];
      if (jobsResult.status === "fulfilled") {
        const first = jobsResult.value.items.find(
          (job) => job.registered_model_version !== null,
        );
        if (first) {
          setModel((value) => value || first.registered_model_name);
          setVersion((value) => value || first.registered_model_version || "");
          setTask(first.trainer_key.task_type);
          if (algorithmsResult.status === "fulfilled") {
            const selected = algorithmsResult.value.find(
              (item) =>
                item.algorithm_family === first.trainer_key.algorithm &&
                item.supported_tasks.includes(first.trainer_key.task_type),
            );
            setAlgorithm(selected?.id ?? "");
          }
        }
      } else if (!isRequestCancelled(jobsResult.reason, controller.signal)) {
        failures.push("Model discovery is unavailable.");
      }
      if (eventsResult.status === "fulfilled") setEvents(eventsResult.value.items);
      else if (!isRequestCancelled(eventsResult.reason, controller.signal))
        failures.push("Recent prediction events are unavailable.");
      if (algorithmsResult.status === "fulfilled")
        setAlgorithms(algorithmsResult.value);
      else if (!isRequestCancelled(algorithmsResult.reason, controller.signal))
        failures.push("Algorithm metadata is unavailable.");
      setLoadWarning(failures.length ? failures.join(" ") : null);
    });
    return () => {
      active = false;
      controller.abort();
    };
  }, [canReadHistory]);

  useEffect(() => {
    if (!model.trim() || !version.trim()) {
      return;
    }
    const controller = new AbortController();
    getFeatureSchema(model.trim(), version.trim(), controller.signal)
      .then((value) => {
        setFeatureSchema(value);
        setTask(value.task_type);
        setAlgorithm(value.algorithm);
        setStructuredValues(
          Object.fromEntries(value.features.map((feature) => [feature.name, ""])),
        );
        setSchemaUnavailable(false);
        setAdvancedInput(false);
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal)) {
          setFeatureSchema(null);
          setSchemaUnavailable(true);
        }
      });
    return () => controller.abort();
  }, [model, version]);

  return (
    <section>
      <PageHeader
        eyebrow="Intelligence operations"
        headingId="predictions-heading"
        title="Predictions"
        description="Execute synchronous registered-model inference. Model choices are discoverable from authorized successful training jobs and are not a complete registry catalog."
        actions={
          canReadHistory ? (
            <Link className="text-sm font-semibold text-link" to="/predictions/history">
              Prediction history
            </Link>
          ) : undefined
        }
      />
      {loadWarning ? (
        <div className="mt-5">
          <InlineNotice>
            {loadWarning} Direct model and version entry remains available.
          </InlineNotice>
        </div>
      ) : null}
      <div className="mt-6 grid gap-6 xl:grid-cols-[1fr_.8fr]">
        <form
          className={panelClassName}
          onSubmit={(event) => {
            event.preventDefault();
            setExecutionError(null);
            setFeatureMatrixInvalid(false);
            setExecutionResult(null);
            setExecutionLoading(true);
            try {
              if (featureSchema !== null && !advancedInput) {
                const values = Object.fromEntries(
                  featureSchema.features.map((feature) => {
                    const raw = structuredValues[feature.name] ?? "";
                    if (!raw.trim())
                      throw new Error(`Enter a value for ${feature.name}.`);
                    const numeric = Number(raw);
                    if (!Number.isFinite(numeric))
                      throw new Error(`${feature.name} must be a finite number.`);
                    return [feature.name, numeric];
                  }),
                );
                void executeStructuredPrediction(model.trim(), version.trim(), values)
                  .then((response) => {
                    setExecutionError(null);
                    setExecutionResult({
                      model_name: response.model_name,
                      model_version: response.model_version,
                      predictions: [response.prediction],
                      trainer_key: {
                        algorithm: featureSchema.algorithm,
                        task_type: featureSchema.task_type,
                      },
                    });
                  })
                  .catch((caught: unknown) => {
                    setExecutionError(executionErrorMessage(caught));
                  })
                  .finally(() => setExecutionLoading(false));
                return;
              }
              const features = parseMatrix(matrix);
              void executePrediction(
                task,
                {
                  registered_model_name: model.trim(),
                  version_or_alias: version.trim(),
                  features,
                },
                undefined,
                algorithm,
              )
                .then((response) => {
                  setExecutionError(null);
                  setExecutionResult(response);
                })
                .catch((caught: unknown) => {
                  setFeatureMatrixInvalid(
                    !(caught instanceof ApiError) ||
                      (caught.status === 422 &&
                        caught.message.toLowerCase().includes("feature matrix")),
                  );
                  setExecutionError(executionErrorMessage(caught));
                })
                .finally(() => setExecutionLoading(false));
            } catch (caught) {
              setFeatureMatrixInvalid(true);
              setExecutionError(executionErrorMessage(caught));
              setExecutionLoading(false);
            }
          }}
        >
          <h2 className="text-lg font-semibold text-foreground">Execute prediction</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <label className="text-sm font-medium text-secondary-foreground">
              Discoverable model or direct name
              <input
                required
                className={inputClassName}
                value={model}
                onChange={(e) => {
                  setModel(e.target.value);
                  setFeatureSchema(null);
                  setSchemaUnavailable(false);
                  setExecutionError(null);
                }}
              />
            </label>
            <label className="text-sm font-medium text-secondary-foreground">
              Exact version or alias
              <input
                required
                className={inputClassName}
                value={version}
                onChange={(e) => {
                  setVersion(e.target.value);
                  setFeatureSchema(null);
                  setSchemaUnavailable(false);
                  setExecutionError(null);
                }}
              />
            </label>
            <label className="text-sm font-medium text-secondary-foreground">
              Task type
              <select
                className={inputClassName}
                value={task}
                onChange={(e) => {
                  setTask(e.target.value as TrainingTask);
                  setExecutionError(null);
                }}
              >
                <option value="regression">Regression</option>
                <option value="classification">Classification</option>
              </select>
            </label>
            <label className="text-sm font-medium text-secondary-foreground">
              Algorithm
              <select
                className={inputClassName}
                onChange={(event) => {
                  setAlgorithm(event.target.value);
                  setExecutionError(null);
                }}
                value={algorithm}
              >
                <option value="">Random Forest compatibility route</option>
                {algorithms
                  .filter((item) => item.supported_tasks.includes(task))
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.display_name}
                    </option>
                  ))}
              </select>
            </label>
          </div>
          {featureSchema !== null && !advancedInput ? (
            <fieldset className="mt-5">
              <legend className="text-sm font-semibold text-foreground">
                Model inputs
              </legend>
              <p className="mt-1 text-xs text-muted-foreground">
                Fields and ranges come from the exact registered model version.
              </p>
              <div className="mt-3 grid gap-4 sm:grid-cols-2">
                {featureSchema.features.map((feature) => (
                  <label
                    className="text-sm font-medium text-secondary-foreground"
                    key={feature.name}
                  >
                    {feature.name}
                    {feature.unit ? ` (${feature.unit})` : ""}
                    <input
                      className={inputClassName}
                      max={feature.maximum ?? undefined}
                      min={feature.minimum ?? undefined}
                      onChange={(event) => {
                        setStructuredValues((current) => ({
                          ...current,
                          [feature.name]: event.target.value,
                        }));
                        setExecutionError(null);
                      }}
                      required={feature.required}
                      step={feature.data_type === "integer" ? 1 : "any"}
                      type="number"
                      value={structuredValues[feature.name] ?? ""}
                    />
                  </label>
                ))}
              </div>
            </fieldset>
          ) : (
            <label className="mt-4 block text-sm font-medium text-secondary-foreground">
              Feature matrix
              <textarea
                aria-describedby="feature-matrix-help"
                aria-invalid={featureMatrixInvalid}
                className={`${inputClassName} min-h-32 font-mono ${featureMatrixInvalid ? "border-danger-600 focus:border-danger-600 focus:ring-danger-600" : ""}`}
                value={matrix}
                onChange={(e) => {
                  setMatrix(e.target.value);
                  setExecutionError(null);
                  setFeatureMatrixInvalid(false);
                }}
              />
            </label>
          )}
          {featureSchema === null && schemaUnavailable ? (
            <div className="mt-3">
              <InlineNotice>
                {canUseAdvancedInput
                  ? "This model version has no governed feature schema. Advanced raw input remains available to engineers and administrators."
                  : "This model version is not available for operator prediction because its governed feature schema is missing."}
              </InlineNotice>
            </div>
          ) : null}
          {featureSchema !== null && canUseAdvancedInput ? (
            <button
              className="mt-3 text-sm font-semibold text-link"
              onClick={() => setAdvancedInput((value) => !value)}
              type="button"
            >
              {advancedInput
                ? "Use governed input form"
                : "Advanced: use raw JSON matrix"}
            </button>
          ) : null}
          <p className="mt-2 text-xs text-muted-foreground" id="feature-matrix-help">
            JSON example: [[0.75, 1.4]]. Rows must be rectangular and contain finite
            numbers.
          </p>
          {executionError ? (
            <div
              className="mt-4 rounded-md border border-danger-200 bg-danger-50 p-4"
              role="alert"
            >
              <h3 className="font-semibold text-danger-900">
                Prediction could not be completed
              </h3>
              <p className="mt-1 text-sm text-danger-800">{executionError}</p>
            </div>
          ) : null}
          <button
            className={`${primaryButtonClassName} mt-5`}
            disabled={executionLoading || (schemaUnavailable && !canUseAdvancedInput)}
            type="submit"
          >
            {executionLoading ? "Running prediction…" : "Run prediction"}
          </button>
        </form>
        <aside className={panelClassName}>
          <h2 className="text-lg font-semibold text-foreground">Result</h2>
          {executionResult ? (
            <div className="mt-4 space-y-4">
              <IntelligenceStatus value="succeeded" />
              <p className="text-sm text-secondary-foreground">
                {executionResult.model_name} · version {executionResult.model_version} ·{" "}
                {executionResult.trainer_key.task_type}
              </p>

              {/* Predictions */}
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Predictions
                </p>
                <div className="mt-1 rounded-md bg-elevated p-4 font-mono text-sm text-foreground">
                  {JSON.stringify(executionResult.predictions)}
                </div>
              </div>

              {/* Class probabilities — rendered when available */}
              {executionResult.probability_available &&
              executionResult.probabilities &&
              executionResult.probabilities.length > 0 ? (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Class probabilities
                  </p>
                  <div className="mt-2 space-y-3">
                    {executionResult.probabilities.map((rowProbs, rowIdx) => (
                      <div
                        className="rounded-md border border-border bg-card p-3"
                        key={rowIdx}
                        aria-label={`Row ${rowIdx + 1} class probabilities`}
                      >
                        <p className="mb-2 text-xs text-muted-foreground">
                          Row {rowIdx + 1}
                        </p>
                        <ul className="space-y-1.5" role="list">
                          {rowProbs.map((prob) => (
                            <li
                              className="flex items-center gap-2 text-xs"
                              key={prob.class_label}
                              role="listitem"
                              aria-label={`Class ${prob.class_label}: ${(prob.probability * 100).toFixed(1)}%`}
                            >
                              <span className="w-12 shrink-0 text-right font-medium text-muted-foreground">
                                {prob.class_label}
                              </span>
                              <div
                                aria-hidden="true"
                                className="flex-1 overflow-hidden rounded-sm bg-muted/30"
                                style={{ height: "1.1rem" }}
                              >
                                <div
                                  className="h-full rounded-sm bg-primary/75 transition-all"
                                  style={{ width: `${prob.probability * 100}%` }}
                                />
                              </div>
                              <span className="w-14 shrink-0 tabular-nums text-muted-foreground">
                                {(prob.probability * 100).toFixed(2)}%
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                </div>
              ) : executionResult.trainer_key.task_type === "classification" &&
                !executionResult.probability_available ? (
                <div
                  className="rounded-md border border-border bg-muted/30 px-4 py-3 text-xs text-muted-foreground"
                  role="note"
                >
                  Class probabilities are not available for this model.
                  {executionResult.probability_unavailable_reason
                    ? ` ${executionResult.probability_unavailable_reason}`
                    : ""}
                </div>
              ) : null}

              <InlineNotice>
                The execution response does not expose an event ID. Authorized history
                is captured separately by the monitoring API.
              </InlineNotice>
            </div>
          ) : (
            <p className="mt-4 text-sm text-muted-foreground">
              Run a prediction to see the confirmed numeric output.
            </p>
          )}
        </aside>
      </div>
      {canReadHistory ? (
        <div className="mt-6">
          <h2 className="text-lg font-semibold text-foreground">
            Recent authorized events
          </h2>
          {events.length ? (
            <div className="mt-3 overflow-x-auto rounded-lg border border-border bg-card">
              <table className="min-w-full text-left text-sm">
                <thead>
                  <tr>
                    <th className="px-4 py-3">Model/version</th>
                    <th className="px-4 py-3">Task</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((item) => (
                    <tr className="border-t border-border" key={item.event_id}>
                      <td className="px-4 py-3">
                        {item.registered_model_name} /{" "}
                        {item.resolved_model_version ?? "unresolved"}
                      </td>
                      <td className="px-4 py-3">{item.trainer_key.task_type}</td>
                      <td className="px-4 py-3">
                        <IntelligenceStatus value={item.status} />
                      </td>
                      <td className="px-4 py-3">
                        <Link
                          className="font-semibold text-link"
                          to={`/predictions/history/${item.event_id}`}
                        >
                          Open
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">
              No prediction events are available.
            </p>
          )}
        </div>
      ) : (
        <div className="mt-6">
          <InlineNotice>
            Operators can execute predictions but prediction-event history is restricted
            to administrators and engineers.
          </InlineNotice>
        </div>
      )}
    </section>
  );
}
