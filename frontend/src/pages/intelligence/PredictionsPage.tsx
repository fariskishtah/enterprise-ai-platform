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
  listPredictionEvents,
  type PredictionEvent,
  type PredictionResponse,
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
            disabled={executionLoading}
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
              <div className="rounded-md bg-elevated p-4 font-mono text-sm text-foreground">
                {JSON.stringify(executionResult.predictions)}
              </div>
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
