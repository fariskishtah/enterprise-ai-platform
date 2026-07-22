import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import { Navigate, useNavigate } from "react-router-dom";

import {
  createAutoMLStudy,
  getAutoMLAlgorithms,
  type AutoMLAlgorithm,
  type AutoMLDataRequest,
  type AutoMLSearchParameter,
  type AutoMLRequestSearchParameter,
  type AutoMLSearchSpace,
  type AutoMLTask,
  type MetricDirection,
} from "../../api/automl";
import { useAuth } from "../../auth/useAuth";
import { RegisteredDatasetVersionSelect } from "../../components/aiLifecycle/RegisteredDatasetVersionSelect";
import {
  InlineNotice,
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { PageHeader } from "../../components/ui/PageHeader";
import { hierarchyError } from "../hierarchy/shared";

const metricCatalog = {
  classification: [
    ["accuracy", "Accuracy", "maximize", false],
    ["precision_macro", "Macro precision", "maximize", false],
    ["recall_macro", "Macro recall", "maximize", false],
    ["f1_macro", "Macro F1", "maximize", false],
    ["roc_auc", "ROC AUC", "maximize", true],
  ],
  regression: [
    ["mae", "Mean absolute error", "minimize", false],
    ["mse", "Mean squared error", "minimize", false],
    ["rmse", "Root mean squared error", "minimize", false],
    ["r2", "R²", "maximize", false],
    ["median_absolute_error", "Median absolute error", "minimize", false],
  ],
} as const;

interface FormState {
  readonly task: AutoMLTask;
  readonly metric: string;
  readonly plugins: readonly string[];
  readonly dataSource: "inline" | "registered";
  readonly datasetVersionId: string;
  readonly trainingFeatures: string;
  readonly trainingTargets: string;
  readonly evaluationFeatures: string;
  readonly evaluationTargets: string;
  readonly folds: number;
  readonly trials: number;
  readonly studyTimeout: number;
  readonly trialTimeout: number;
  readonly concurrency: number;
  readonly seed: number;
  readonly scaler: string;
  readonly imputer: string;
  readonly registerChampion: boolean;
  readonly modelName: string;
}

const initial: FormState = {
  concurrency: 1,
  dataSource: "inline",
  datasetVersionId: "",
  evaluationFeatures: "",
  evaluationTargets: "",
  folds: 2,
  imputer: "none",
  metric: "rmse",
  modelName: "",
  plugins: [],
  registerChampion: false,
  scaler: "auto",
  seed: 17,
  studyTimeout: 300,
  task: "regression",
  trainingFeatures: "",
  trainingTargets: "",
  trialTimeout: 60,
  trials: 2,
};

export function AutoMLCreatePage(): ReactElement {
  const { role } = useAuth();
  const navigate = useNavigate();
  const [algorithms, setAlgorithms] = useState<readonly AutoMLAlgorithm[]>([]);
  const [form, setForm] = useState<FormState>(initial);
  const [spaces, setSpaces] = useState<
    Readonly<Record<string, readonly AutoMLSearchParameter[]>>
  >({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const idempotencyKey = useRef(crypto.randomUUID());
  const submissionInFlight = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    getAutoMLAlgorithms(controller.signal)
      .then((items) => {
        setAlgorithms(items);
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(hierarchyError(caught));
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, []);

  const metrics = metricCatalog[form.task];
  const selectedMetric = metrics.find(([key]) => key === form.metric) ?? metrics[0];
  const compatible = useMemo(
    () => algorithms.filter((item) => item.task_type === form.task),
    [algorithms, form.task],
  );
  if (role === "operator") return <Navigate replace to="/" />;

  const update = <K extends keyof FormState>(key: K, value: FormState[K]): void =>
    setForm((current) => ({ ...current, [key]: value }));
  const selectTask = (task: AutoMLTask): void => {
    update("task", task);
    setForm((current) => ({
      ...current,
      metric: metricCatalog[task][0][0],
      plugins: [],
      task,
    }));
    setSpaces({});
  };
  const togglePlugin = (algorithm: AutoMLAlgorithm, checked: boolean): void => {
    setForm((current) => ({
      ...current,
      plugins: checked
        ? [...current.plugins, algorithm.id]
        : current.plugins.filter((id) => id !== algorithm.id),
    }));
    setSpaces((current) =>
      checked
        ? { ...current, [algorithm.id]: algorithm.parameters }
        : Object.fromEntries(
            Object.entries(current).filter(([id]) => id !== algorithm.id),
          ),
    );
  };
  const narrowNumber = (
    pluginId: string,
    parameterName: string,
    key: "low" | "high",
    value: number,
  ): void => {
    setSpaces((current) => ({
      ...current,
      [pluginId]: (current[pluginId] ?? []).map((parameter) =>
        parameter.name === parameterName ? { ...parameter, [key]: value } : parameter,
      ),
    }));
  };
  const toggleChoice = (
    pluginId: string,
    parameterName: string,
    choice: AutoMLSearchParameter["default"],
    checked: boolean,
  ): void => {
    setSpaces((current) => ({
      ...current,
      [pluginId]: (current[pluginId] ?? []).map((parameter) =>
        parameter.name === parameterName
          ? {
              ...parameter,
              choices: checked
                ? [...parameter.choices, choice]
                : parameter.choices.filter((item) => item !== choice),
            }
          : parameter,
      ),
    }));
  };

  const submit = async (): Promise<void> => {
    if (submissionInFlight.current) return;
    submissionInFlight.current = true;
    setSubmitting(true);
    setError(null);
    try {
      let data: AutoMLDataRequest;
      if (form.dataSource === "registered") {
        if (form.datasetVersionId === "")
          throw new Error("Select a ready registered dataset version.");
        data = { dataset_version_id: form.datasetVersionId };
      } else {
        const trainingFeatures = parseMatrix(
          form.trainingFeatures,
          "Training features",
        );
        const evaluationFeatures = parseMatrix(
          form.evaluationFeatures,
          "Evaluation features",
        );
        const trainingTargets = parseVector(
          form.trainingTargets,
          form.task,
          "Training targets",
        );
        const evaluationTargets = parseVector(
          form.evaluationTargets,
          form.task,
          "Evaluation targets",
        );
        validateRows(
          trainingFeatures,
          trainingTargets,
          evaluationFeatures,
          evaluationTargets,
          form.folds,
          form.task,
        );
        data = {
          evaluation_data_fingerprint: await digest(
            JSON.stringify([evaluationFeatures, evaluationTargets]),
          ),
          evaluation_features: evaluationFeatures,
          evaluation_row_count: evaluationFeatures.length,
          evaluation_targets: evaluationTargets,
          feature_count: trainingFeatures[0].length,
          training_data_fingerprint: await digest(
            JSON.stringify([trainingFeatures, trainingTargets]),
          ),
          training_features: trainingFeatures,
          training_row_count: trainingFeatures.length,
          training_targets: trainingTargets,
        };
      }
      if (form.concurrency > form.trials)
        throw new Error("Max concurrent trials cannot exceed the trial budget.");
      if (form.trialTimeout > form.studyTimeout)
        throw new Error("Per-trial timeout cannot exceed the study timeout.");
      if (
        form.registerChampion &&
        (form.modelName.trim().length < 3 || form.modelName.trim().length > 128)
      )
        throw new Error("Registered model name must be between 3 and 128 characters.");
      if (form.plugins.length === 0)
        throw new Error("Select at least one compatible algorithm.");
      if (
        selectedMetric[3] &&
        form.plugins.some(
          (id) => !algorithms.find((item) => item.id === id)?.probability_support,
        )
      )
        throw new Error(
          "Every selected algorithm must support probabilities for ROC AUC.",
        );
      const selectedSpaces: AutoMLSearchSpace[] = form.plugins.map((id) => {
        const algorithm = algorithms.find((item) => item.id === id);
        if (algorithm === undefined)
          throw new Error("A selected algorithm is no longer available.");
        const parameters = spaces[id] ?? algorithm.parameters;
        validateNarrowing(algorithm.parameters, parameters);
        return {
          parameters: parameters.map(toRequestParameter),
          plugin_id: id,
          probability_support: algorithm.probability_support,
          task_type: form.task,
        };
      });
      const submission = await createAutoMLStudy(
        {
          budget: {
            cross_validation_folds: form.folds,
            max_concurrent_trials: form.concurrency,
            per_trial_timeout_seconds: form.trialTimeout,
            time_budget_seconds: form.studyTimeout,
            trial_budget: form.trials,
          },
          data,
          metric_direction: selectedMetric[2] as MetricDirection,
          plugin_ids: form.plugins,
          plugin_search_spaces: selectedSpaces,
          preprocessing: { imputer: form.imputer, scaler: form.scaler },
          primary_metric: selectedMetric[0],
          random_seed: form.seed,
          register_champion: form.registerChampion,
          registered_model_name: form.registerChampion ? form.modelName.trim() : null,
          sampler_type: "random",
          task_type: form.task,
        },
        idempotencyKey.current,
      );
      navigate(`/automl/studies/${submission.study_id}`, {
        state: {
          notice: submission.created
            ? "AutoML study submitted."
            : "Existing idempotent study opened.",
        },
      });
    } catch (caught) {
      setError(hierarchyError(caught));
      submissionInFlight.current = false;
      setSubmitting(false);
    }
  };

  return (
    <section aria-labelledby="automl-create-heading">
      <PageHeader
        description="Configure a bounded cross-validation study using approved algorithms and explicit data."
        eyebrow="AutoML Studio"
        headingId="automl-create-heading"
        title="Create AutoML study"
      />
      <div className="mt-6 space-y-6">
        <InlineNotice>
          AutoML consumes CPU and time. Trial results are cross-validation estimates.
          Initial global execution concurrency is one.
        </InlineNotice>
        {error === null ? null : (
          <div
            className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800"
            role="alert"
          >
            {error}
          </div>
        )}
        <fieldset className="rounded-lg border border-border bg-card p-5">
          <legend className="px-2 font-semibold">Objective</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <Select
              label="Task type"
              value={form.task}
              onChange={(value) => selectTask(value as AutoMLTask)}
            >
              <option value="regression">Regression</option>
              <option value="classification">Classification</option>
            </Select>
            <Select
              label="Primary metric"
              value={form.metric}
              onChange={(value) => update("metric", value)}
            >
              {metrics.map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </Select>
          </div>
          <p className="mt-3 text-sm text-muted-foreground">
            Direction: <strong>{selectedMetric[2]}</strong>
            {selectedMetric[3] ? " · Requires probability-capable algorithms." : ""}
          </p>
        </fieldset>
        <fieldset className="rounded-lg border border-border bg-card p-5">
          <legend className="px-2 font-semibold">Algorithms</legend>
          {loading ? (
            <p>Loading approved algorithms…</p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {compatible.map((algorithm) => (
                <label
                  className="rounded-md border border-border bg-secondary p-4"
                  key={algorithm.id}
                >
                  <span className="flex gap-3">
                    <input
                      checked={form.plugins.includes(algorithm.id)}
                      onChange={(event) =>
                        togglePlugin(algorithm, event.target.checked)
                      }
                      type="checkbox"
                    />
                    <span>
                      <strong>{algorithm.display_name}</strong>
                      <span className="block text-xs text-muted-foreground">
                        {algorithm.id}
                        {algorithm.probability_support ? " · probabilities" : ""}
                      </span>
                    </span>
                  </span>
                  {form.plugins.includes(algorithm.id) ? (
                    <details className="mt-3">
                      <summary className="cursor-pointer text-sm font-semibold text-purple-700">
                        Narrow search space
                      </summary>
                      <div className="mt-3 space-y-3">
                        {(spaces[algorithm.id] ?? []).map((parameter) => (
                          <ParameterControl
                            approvedChoices={
                              algorithm.parameters.find(
                                (item) => item.name === parameter.name,
                              )?.choices ?? []
                            }
                            key={parameter.name}
                            parameter={parameter}
                            onNumber={(key, value) =>
                              narrowNumber(algorithm.id, parameter.name, key, value)
                            }
                            onChoice={(choice, checked) =>
                              toggleChoice(
                                algorithm.id,
                                parameter.name,
                                choice,
                                checked,
                              )
                            }
                          />
                        ))}
                      </div>
                    </details>
                  ) : null}
                </label>
              ))}
            </div>
          )}
        </fieldset>
        <fieldset className="rounded-lg border border-border bg-card p-5">
          <legend className="px-2 font-semibold">Bounded data</legend>
          <p className="mb-4 text-sm text-muted-foreground">
            Select an immutable ready dataset version or provide bounded matrices
            inline. The two sources are mutually exclusive.
          </p>
          <div className="mb-5 flex flex-wrap gap-4">
            <label className="flex items-center gap-2 text-sm">
              <input
                checked={form.dataSource === "inline"}
                name="automl-data-source"
                onChange={() => {
                  update("dataSource", "inline");
                  setError(null);
                }}
                type="radio"
              />
              Inline matrices
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                checked={form.dataSource === "registered"}
                name="automl-data-source"
                onChange={() => {
                  update("dataSource", "registered");
                  setError(null);
                }}
                type="radio"
              />
              Registered dataset version
            </label>
          </div>
          {form.dataSource === "registered" ? (
            <RegisteredDatasetVersionSelect
              disabled={submitting}
              id="automl-dataset-version"
              onChange={(value) => update("datasetVersionId", value)}
              value={form.datasetVersionId}
            />
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              <TextArea
                label="Training features"
                value={form.trainingFeatures}
                onChange={(value) => update("trainingFeatures", value)}
                placeholder={"0.1, 1.2\n0.4, 1.8"}
              />
              <TextArea
                label="Training targets"
                value={form.trainingTargets}
                onChange={(value) => update("trainingTargets", value)}
                placeholder="0, 1"
              />
              <TextArea
                label="Evaluation features"
                value={form.evaluationFeatures}
                onChange={(value) => update("evaluationFeatures", value)}
                placeholder={"0.2, 1.4\n0.5, 2.0"}
              />
              <TextArea
                label="Evaluation targets"
                value={form.evaluationTargets}
                onChange={(value) => update("evaluationTargets", value)}
                placeholder="0, 1"
              />
            </div>
          )}
        </fieldset>
        <details className="rounded-lg border border-border bg-card p-5">
          <summary className="cursor-pointer font-semibold">Advanced controls</summary>
          <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <NumberField
              label="Trial budget"
              min={1}
              max={100}
              value={form.trials}
              onChange={(value) => update("trials", value)}
            />
            <NumberField
              label="CV folds"
              min={2}
              max={10}
              value={form.folds}
              onChange={(value) => update("folds", value)}
            />
            <NumberField
              label="Study timeout (seconds)"
              min={60}
              max={86400}
              value={form.studyTimeout}
              onChange={(value) => update("studyTimeout", value)}
            />
            <NumberField
              label="Per-trial timeout (seconds)"
              min={10}
              max={21600}
              value={form.trialTimeout}
              onChange={(value) => update("trialTimeout", value)}
            />
            <NumberField
              label="Max concurrent trials"
              min={1}
              max={4}
              value={form.concurrency}
              onChange={(value) => update("concurrency", value)}
            />
            <NumberField
              label="Random seed"
              value={form.seed}
              onChange={(value) => update("seed", value)}
            />
            <Select
              label="Scaler"
              value={form.scaler}
              onChange={(value) => update("scaler", value)}
            >
              <option value="auto">Auto</option>
              <option value="none">None</option>
              <option value="standard">Standard</option>
              <option value="minmax">Min-max</option>
              <option value="robust">Robust</option>
            </Select>
            <Select
              label="Imputer"
              value={form.imputer}
              onChange={(value) => update("imputer", value)}
            >
              <option value="none">None</option>
              <option value="mean">Mean</option>
              <option value="median">Median</option>
              <option value="most_frequent">Most frequent</option>
            </Select>
          </div>
        </details>
        <fieldset className="rounded-lg border border-border bg-card p-5">
          <legend className="px-2 font-semibold">Champion handoff</legend>
          <label className="flex gap-3">
            <input
              checked={form.registerChampion}
              onChange={(event) => update("registerChampion", event.target.checked)}
              type="checkbox"
            />
            <span>
              <strong>Retrain and register the winning configuration</strong>
              <span className="block text-sm text-muted-foreground">
                Uses the existing ordinary training pipeline; AutoML does not assign a
                production champion alias.
              </span>
            </span>
          </label>
          {form.registerChampion ? (
            <label className="mt-4 block text-sm font-medium">
              Registered model name
              <input
                className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
                onChange={(event) => update("modelName", event.target.value)}
                required
                value={form.modelName}
              />
            </label>
          ) : null}
        </fieldset>
        <InlineNotice>
          Running sklearn fits may be terminated when a timeout expires or cancellation
          is requested. Queued work stops first; active work may take a short time to
          terminate.
        </InlineNotice>
        <div className="flex justify-end gap-3">
          <button
            className={secondaryButtonClassName}
            onClick={() => navigate("/automl")}
            type="button"
          >
            Cancel
          </button>
          <button
            className={primaryButtonClassName}
            disabled={submitting || loading}
            onClick={() => void submit()}
            type="button"
          >
            {submitting ? "Submitting…" : "Create and start study"}
          </button>
        </div>
      </div>
    </section>
  );
}

function parseMatrix(value: string, label: string): number[][] {
  const rows = value
    .trim()
    .split(/\n+/)
    .filter(Boolean)
    .map((row) => row.split(",").map(Number));
  if (
    rows.length < 2 ||
    rows.some(
      (row) => row.length === 0 || row.some((item) => !Number.isFinite(item)),
    ) ||
    new Set(rows.map((row) => row.length)).size !== 1
  )
    throw new Error(`${label} must contain at least two finite, equal-width rows.`);
  return rows;
}
function parseVector(value: string, task: AutoMLTask, label: string): number[] {
  const values = value
    .split(/[\s,]+/)
    .filter(Boolean)
    .map(Number);
  if (
    values.length < 2 ||
    values.some((item) => !Number.isFinite(item)) ||
    (task === "classification" && values.some((item) => !Number.isInteger(item)))
  )
    throw new Error(
      `${label} must contain at least two ${task === "classification" ? "integer " : ""}values.`,
    );
  return values;
}
function validateRows(
  trainX: number[][],
  trainY: number[],
  evalX: number[][],
  evalY: number[],
  folds: number,
  task: AutoMLTask,
): void {
  if (trainX.length !== trainY.length || evalX.length !== evalY.length)
    throw new Error("Each feature row must have one target.");
  if (trainX[0].length !== evalX[0].length)
    throw new Error("Training and evaluation feature widths must match.");
  if (task === "classification") {
    const counts = Object.values(
      trainY.reduce<Record<string, number>>(
        (result, value) => ({ ...result, [value]: (result[value] ?? 0) + 1 }),
        {},
      ),
    );
    if (counts.length < 2 || Math.min(...counts) < folds)
      throw new Error(
        "Classification requires two classes and at least one sample per class for every CV fold.",
      );
  }
}
function validateNarrowing(
  owned: readonly AutoMLSearchParameter[],
  narrowed: readonly AutoMLSearchParameter[],
): void {
  for (const parameter of narrowed) {
    const source = owned.find((item) => item.name === parameter.name);
    if (source === undefined)
      throw new Error("Search-space parameters cannot be added.");
    if (
      (parameter.low !== null && source.low !== null && parameter.low < source.low) ||
      (parameter.high !== null &&
        source.high !== null &&
        parameter.high > source.high) ||
      (parameter.low !== null &&
        parameter.high !== null &&
        parameter.low > parameter.high)
    )
      throw new Error(`${parameter.name} must remain inside its approved bounds.`);
    if (parameter.kind === "categorical") {
      if (
        parameter.choices.length === 0 ||
        parameter.choices.some(
          (choice) => !source.choices.some((approved) => approved === choice),
        )
      )
        throw new Error(`${parameter.name} must retain at least one approved choice.`);
      if (!parameter.choices.some((choice) => choice === parameter.default))
        throw new Error(`${parameter.name} must retain its approved default choice.`);
    }
  }
}

function toRequestParameter(
  parameter: AutoMLSearchParameter,
): AutoMLRequestSearchParameter {
  if (parameter.kind === "categorical") {
    return {
      choices: parameter.choices,
      default: parameter.default,
      kind: parameter.kind,
      name: parameter.name,
    };
  }
  if (
    typeof parameter.default !== "number" ||
    parameter.low === null ||
    parameter.high === null
  ) {
    throw new Error(`${parameter.name} has incomplete numeric bounds.`);
  }
  if (parameter.kind === "integer") {
    if (parameter.step === null) {
      throw new Error(`${parameter.name} has no integer step.`);
    }
    return {
      default: parameter.default,
      high: parameter.high,
      kind: parameter.kind,
      log_scale: false,
      low: parameter.low,
      name: parameter.name,
      step: parameter.step,
    };
  }
  return {
    default: parameter.default,
    high: parameter.high,
    kind: parameter.kind,
    log_scale: parameter.log_scale,
    low: parameter.low,
    name: parameter.name,
    step: parameter.step,
  };
}
async function digest(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
function Select({
  children,
  label,
  onChange,
  value,
}: {
  readonly children: ReactNode;
  readonly label: string;
  readonly onChange: (value: string) => void;
  readonly value: string;
}): ReactElement {
  return (
    <label className="block text-sm font-medium">
      {label}
      <select
        className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
        onChange={(event) => onChange(event.target.value)}
        value={value}
      >
        {children}
      </select>
    </label>
  );
}
function NumberField({
  label,
  max,
  min,
  onChange,
  value,
}: {
  readonly label: string;
  readonly max?: number;
  readonly min?: number;
  readonly onChange: (value: number) => void;
  readonly value: number;
}): ReactElement {
  return (
    <label className="block text-sm font-medium">
      {label}
      <input
        className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
        max={max}
        min={min}
        onChange={(event) => onChange(event.currentTarget.valueAsNumber)}
        type="number"
        value={value}
      />
    </label>
  );
}
function TextArea({
  label,
  onChange,
  placeholder,
  value,
}: {
  readonly label: string;
  readonly onChange: (value: string) => void;
  readonly placeholder: string;
  readonly value: string;
}): ReactElement {
  return (
    <label className="block text-sm font-medium">
      {label}
      <textarea
        className="mt-1 min-h-24 w-full rounded-md border border-border-strong bg-elevated px-3 py-2 font-mono text-sm"
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        required
        value={value}
      />
    </label>
  );
}
function ParameterControl({
  approvedChoices,
  onChoice,
  onNumber,
  parameter,
}: {
  readonly approvedChoices: readonly AutoMLSearchParameter["default"][];
  readonly onChoice: (
    choice: AutoMLSearchParameter["default"],
    checked: boolean,
  ) => void;
  readonly onNumber: (key: "low" | "high", value: number) => void;
  readonly parameter: AutoMLSearchParameter;
}): ReactElement {
  return (
    <div className="rounded border border-border bg-card p-3 text-sm">
      <strong>{parameter.name}</strong>
      {parameter.kind === "categorical" ? (
        <fieldset className="mt-2">
          <legend className="text-xs text-muted-foreground">
            Retain approved choices
          </legend>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-2">
            {approvedChoices.map((choice) => (
              <label className="flex items-center gap-2" key={String(choice)}>
                <input
                  checked={parameter.choices.some((item) => item === choice)}
                  disabled={choice === parameter.default}
                  onChange={(event) => onChoice(choice, event.target.checked)}
                  type="checkbox"
                />
                {String(choice)}
              </label>
            ))}
          </div>
        </fieldset>
      ) : (
        <div className="mt-2 grid grid-cols-2 gap-2">
          <NumberField
            label="Minimum"
            value={parameter.low ?? 0}
            onChange={(value) => onNumber("low", value)}
          />
          <NumberField
            label="Maximum"
            value={parameter.high ?? 0}
            onChange={(value) => onNumber("high", value)}
          />
        </div>
      )}
    </div>
  );
}
