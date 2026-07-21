import { useEffect, useMemo, useState, type FormEvent, type ReactElement } from "react";

import {
  createTrainingJob,
  listAlgorithms,
  type Algorithm,
  type TrainingRequest,
  type TrainingTask,
} from "../../api/aiLifecycle";
import { Dialog } from "../hierarchy/Dialogs";
import {
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../hierarchy/ResourceStates";

const examples = {
  classification: {
    features: "[[0, 0], [0, 1], [1, 0], [1, 1]]",
    targets: "[0, 0, 1, 1]",
  },
  regression: { features: "[[0, 0], [1, 1], [2, 2], [3, 3]]", targets: "[0, 2, 4, 6]" },
} as const;

function parseMatrix(value: string, label: string): number[][] {
  const parsed: unknown = JSON.parse(value);
  if (
    !Array.isArray(parsed) ||
    parsed.length === 0 ||
    parsed.some(
      (row) =>
        !Array.isArray(row) ||
        row.length === 0 ||
        row.some((cell) => typeof cell !== "number" || !Number.isFinite(cell)),
    )
  ) {
    throw new Error(`${label} must be a non-empty JSON matrix of finite numbers.`);
  }
  const matrix = parsed as number[][];
  if (matrix.some((row) => row.length !== matrix[0].length))
    throw new Error(`${label} rows must have equal column counts.`);
  return matrix;
}

function parseTargets(value: string, label: string, integers: boolean): number[] {
  const parsed: unknown = JSON.parse(value);
  if (
    !Array.isArray(parsed) ||
    parsed.length === 0 ||
    parsed.some(
      (item) =>
        typeof item !== "number" ||
        !Number.isFinite(item) ||
        (integers && !Number.isInteger(item)),
    )
  ) {
    throw new Error(
      `${label} must be a non-empty JSON array of ${integers ? "integers" : "finite numbers"}.`,
    );
  }
  return parsed as number[];
}

function parseObject(value: string, label: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))
    throw new Error(`${label} must be a JSON object.`);
  return parsed as Record<string, unknown>;
}

export function TrainingJobFormDialog({
  onClose,
  onCreated,
}: {
  readonly onClose: () => void;
  readonly onCreated: (id: string) => void;
}): ReactElement {
  const [task, setTask] = useState<TrainingTask>("regression");
  const [trainingFeatures, setTrainingFeatures] = useState<string>(
    examples.regression.features,
  );
  const [trainingTargets, setTrainingTargets] = useState<string>(
    examples.regression.targets,
  );
  const [evaluationFeatures, setEvaluationFeatures] = useState(
    "[[0.5, 0.5], [2.5, 2.5]]",
  );
  const [evaluationTargets, setEvaluationTargets] = useState("[1, 5]");
  const [algorithms, setAlgorithms] = useState<readonly Algorithm[]>([]);
  const [algorithmId, setAlgorithmId] = useState("");
  const [parameterValues, setParameterValues] = useState<Record<string, unknown>>({});
  const [scaler, setScaler] = useState("auto");
  const [imputer, setImputer] = useState("none");
  const [tags, setTags] = useState("{}");
  const [seed, setSeed] = useState("17");
  const [experiment, setExperiment] = useState("AI Lifecycle");
  const [runName, setRunName] = useState("");
  const [modelName, setModelName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const availableAlgorithms = useMemo(
    () => algorithms.filter((item) => item.supported_tasks.includes(task)),
    [algorithms, task],
  );
  const algorithm = availableAlgorithms.find((item) => item.id === algorithmId);

  useEffect(() => {
    const controller = new AbortController();
    listAlgorithms(controller.signal)
      .then((items) => {
        setAlgorithms(items);
        const initial = items.find((item) =>
          item.supported_tasks.includes("regression"),
        );
        if (initial) {
          setAlgorithmId(initial.id);
          setParameterValues(initial.default_parameters);
        }
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted)
          setError(
            caught instanceof Error ? caught.message : "Unable to load algorithms.",
          );
      });
    return () => controller.abort();
  }, []);

  const changeTask = (next: TrainingTask): void => {
    setTask(next);
    setTrainingFeatures(examples[next].features);
    setTrainingTargets(examples[next].targets);
    setEvaluationFeatures(
      next === "regression" ? "[[0.5, 0.5], [2.5, 2.5]]" : "[[0, 0.5], [1, 0.5]]",
    );
    setEvaluationTargets(next === "regression" ? "[1, 5]" : "[0, 1]");
    const selected = algorithms.find((item) => item.supported_tasks.includes(next));
    setAlgorithmId(selected?.id ?? "");
    setParameterValues(selected?.default_parameters ?? {});
    setScaler("auto");
  };

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    setError(null);
    try {
      const trainX = parseMatrix(trainingFeatures, "Training features");
      const evaluateX = parseMatrix(evaluationFeatures, "Evaluation features");
      const trainY = parseTargets(
        trainingTargets,
        "Training targets",
        task === "classification",
      );
      const evaluateY = parseTargets(
        evaluationTargets,
        "Evaluation targets",
        task === "classification",
      );
      if (trainX.length !== trainY.length)
        throw new Error("Training feature and target row counts must match.");
      if (evaluateX.length !== evaluateY.length)
        throw new Error("Evaluation feature and target row counts must match.");
      if (trainX[0].length !== evaluateX[0].length)
        throw new Error("Training and evaluation feature column counts must match.");
      const rawTags = parseObject(tags, "Tags");
      if (Object.values(rawTags).some((value) => typeof value !== "string"))
        throw new Error("Every tag value must be a string.");
      if (!/^[-+]?\d+$/.test(seed.trim()))
        throw new Error("Random seed must be an integer.");
      if (experiment.trim() === "") throw new Error("Experiment name is required.");
      const payload: TrainingRequest = {
        evaluation_features: evaluateX,
        evaluation_targets: evaluateY,
        experiment_name: experiment.trim(),
        hyperparameters: parameterValues,
        model_description: description.trim() || null,
        random_seed: Number(seed),
        registered_model_name: modelName.trim() || null,
        run_name: runName.trim() || null,
        tags: rawTags as Record<string, string>,
        training_features: trainX,
        training_targets: trainY,
      };
      setBusy(true);
      if (!algorithm) throw new Error("Select an available algorithm.");
      const result = await createTrainingJob(task, payload, algorithm.id, {
        imputer,
        scaler,
      });
      onCreated(result.job_id);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Unable to submit the training job.",
      );
      setBusy(false);
    }
  };

  const field = (
    id: string,
    label: string,
    value: string,
    setter: (value: string) => void,
    rows = 3,
  ): ReactElement => (
    <div>
      <label className="block text-sm font-medium" htmlFor={id}>
        {label}
      </label>
      <textarea
        className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 font-mono text-sm"
        id={id}
        onChange={(e) => setter(e.target.value)}
        required
        rows={rows}
        value={value}
      />
    </div>
  );

  return (
    <Dialog
      description="Submit one bounded allowlisted job. Algorithm controls come from the backend catalog."
      onClose={onClose}
      title="Create training job"
    >
      <form className="space-y-4" onSubmit={(event) => void submit(event)}>
        <fieldset>
          <legend className="text-sm font-medium">Training mode</legend>
          <div className="mt-2 flex gap-4">
            {(["regression", "classification"] as const).map((value) => (
              <label className="flex items-center gap-2 text-sm" key={value}>
                <input
                  checked={task === value}
                  name="task"
                  onChange={() => changeTask(value)}
                  type="radio"
                />
                {value}
              </label>
            ))}
          </div>
        </fieldset>
        <div>
          <label className="block text-sm font-medium" htmlFor="algorithm">
            Algorithm
          </label>
          <select
            className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm"
            id="algorithm"
            onChange={(event) => {
              const selected = availableAlgorithms.find(
                (item) => item.id === event.target.value,
              );
              setAlgorithmId(event.target.value);
              setParameterValues(selected?.default_parameters ?? {});
            }}
            required
            value={algorithmId}
          >
            {availableAlgorithms.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name}
              </option>
            ))}
          </select>
          {algorithm ? (
            <p className="mt-2 text-sm text-muted-foreground">
              {algorithm.description} Scaling: {algorithm.scaling_behavior}. Global
              explanation:{" "}
              {algorithm.global_explainability ? "available" : "unavailable"}; local
              explanation:{" "}
              {algorithm.local_explainability ? "available" : "unavailable"}.
            </p>
          ) : null}
        </div>
        <p className="rounded-md bg-neutral-100 p-3 text-xs text-neutral-700">
          Compact valid example: features {examples[task].features}; targets{" "}
          {examples[task].targets}.
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          {field(
            "training-features",
            "Training features (JSON matrix)",
            trainingFeatures,
            setTrainingFeatures,
          )}
          {field(
            "training-targets",
            `Training targets (${task === "classification" ? "integer " : ""}JSON array)`,
            trainingTargets,
            setTrainingTargets,
          )}
          {field(
            "evaluation-features",
            "Evaluation features (JSON matrix)",
            evaluationFeatures,
            setEvaluationFeatures,
          )}
          {field(
            "evaluation-targets",
            "Evaluation targets (JSON array)",
            evaluationTargets,
            setEvaluationTargets,
          )}
        </div>
        {algorithm && algorithm.parameters.length ? (
          <fieldset className="grid gap-4 rounded-md border border-border p-4 sm:grid-cols-2">
            <legend className="px-1 text-sm font-medium">Hyperparameters</legend>
            {algorithm.parameters.map((parameter) => (
              <label className="text-sm" key={parameter.name}>
                <span className="block font-medium">{parameter.name}</span>
                {parameter.type === "boolean" ? (
                  <input
                    checked={Boolean(parameterValues[parameter.name])}
                    className="mt-2"
                    onChange={(event) =>
                      setParameterValues((values) => ({
                        ...values,
                        [parameter.name]: event.target.checked,
                      }))
                    }
                    type="checkbox"
                  />
                ) : parameter.type === "choice" ? (
                  <select
                    className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2"
                    onChange={(event) =>
                      setParameterValues((values) => ({
                        ...values,
                        [parameter.name]: event.target.value,
                      }))
                    }
                    value={String(parameterValues[parameter.name])}
                  >
                    {parameter.choices.map((choice) => (
                      <option key={choice}>{choice}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2"
                    max={parameter.maximum ?? undefined}
                    min={parameter.minimum ?? undefined}
                    onChange={(event) =>
                      setParameterValues((values) => ({
                        ...values,
                        [parameter.name]: Number(event.target.value),
                      }))
                    }
                    step={parameter.type === "integer" ? 1 : "any"}
                    type="number"
                    value={Number(parameterValues[parameter.name])}
                  />
                )}
                {parameter.description ? (
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {parameter.description}
                  </span>
                ) : null}
              </label>
            ))}
          </fieldset>
        ) : null}
        <details>
          <summary className="cursor-pointer text-sm font-medium">
            Preprocessing
          </summary>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <label className="text-sm">
              <span className="block font-medium">Numeric scaler</span>
              <select
                className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2"
                onChange={(event) => setScaler(event.target.value)}
                value={scaler}
              >
                {["auto", "none", "standard", "minmax", "robust"].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="block font-medium">Numeric imputer</span>
              <select
                className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2"
                onChange={(event) => setImputer(event.target.value)}
                value={imputer}
              >
                {["none", "mean", "median", "most_frequent"].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
          </div>
        </details>
        {field("tags", "Tags (JSON string map)", tags, setTags, 2)}
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-sm font-medium" htmlFor="experiment">
              Experiment name *
            </label>
            <input
              className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm"
              id="experiment"
              onChange={(e) => setExperiment(e.target.value)}
              required
              value={experiment}
            />
          </div>
          <div>
            <label className="block text-sm font-medium" htmlFor="seed">
              Random seed *
            </label>
            <input
              className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm"
              id="seed"
              inputMode="numeric"
              onChange={(e) => setSeed(e.target.value)}
              required
              value={seed}
            />
          </div>
          <div>
            <label className="block text-sm font-medium" htmlFor="run-name">
              Run name (optional)
            </label>
            <input
              className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm"
              id="run-name"
              onChange={(e) => setRunName(e.target.value)}
              value={runName}
            />
          </div>
          <div>
            <label className="block text-sm font-medium" htmlFor="model-name">
              Registered model name (optional)
            </label>
            <input
              className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm"
              id="model-name"
              onChange={(e) => setModelName(e.target.value)}
              value={modelName}
            />
          </div>
        </div>
        <div>
          <label className="block text-sm font-medium" htmlFor="model-description">
            Model description (optional)
          </label>
          <input
            className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm"
            id="model-description"
            onChange={(e) => setDescription(e.target.value)}
            value={description}
          />
        </div>
        {error === null ? null : (
          <p
            className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800"
            role="alert"
          >
            {error}
          </p>
        )}
        <div className="flex justify-end gap-3">
          <button
            className={secondaryButtonClassName}
            disabled={busy}
            onClick={onClose}
            type="button"
          >
            Cancel
          </button>
          <button className={primaryButtonClassName} disabled={busy} type="submit">
            {busy ? "Submitting…" : "Submit training job"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
