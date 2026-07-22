import { useEffect, useState, type ReactElement } from "react";
import { Link, useParams } from "react-router-dom";

import {
  getTrainingEvaluation,
  getTrainingJob,
  type ClassificationReport,
  type ClassReportRow,
  type EvaluationPayload,
  type ExplainabilityEntry,
  type RankedFeature,
  type TrainingJob,
} from "../../api/aiLifecycle";
import {
  ChartPanel,
  ConfusionMatrix,
  HistogramChart,
  HorizontalBarChart,
  LineSeriesChart,
  MetricCard,
  ScatterChart,
} from "../../components/charts";
import { PageHeader } from "../../components/ui/PageHeader";
import {
  InlineError,
  LoadingSkeleton,
} from "../../components/hierarchy/ResourceStates";

// ─── Type guards ──────────────────────────────────────────────────────────────

function isRankedFeatureList(
  entry: ExplainabilityEntry | undefined,
): entry is readonly RankedFeature[] {
  return Array.isArray(entry);
}

function explainabilityReason(entry: ExplainabilityEntry | undefined): string {
  if (entry === undefined || isRankedFeatureList(entry)) return "Not available.";
  return entry.reason;
}

function isClassReportRow(value: unknown): value is ClassReportRow {
  return (
    value !== null &&
    typeof value === "object" &&
    "precision" in value &&
    "recall" in value &&
    "f1-score" in value
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function BadgePill({
  children,
  variant = "default",
}: {
  children: React.ReactNode;
  variant?: "default" | "classification" | "regression";
}): ReactElement {
  const colorMap = {
    default: "bg-muted text-muted-foreground",
    classification:
      "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-200",
    regression: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${colorMap[variant]}`}
    >
      {children}
    </span>
  );
}

function SectionDivider({ title }: { title: string }): ReactElement {
  return (
    <div className="flex items-center gap-3">
      <div className="h-px flex-1 bg-border" />
      <span className="shrink-0 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
        {title}
      </span>
      <div className="h-px flex-1 bg-border" />
    </div>
  );
}

function ClassificationReportTable({
  report,
}: {
  report: ClassificationReport;
}): ReactElement {
  const classRows = Object.entries(report).filter(
    ([key, value]) =>
      isClassReportRow(value) &&
      key !== "accuracy" &&
      key !== "macro avg" &&
      key !== "weighted avg",
  );
  const macroAvg = report["macro avg"];
  const weightedAvg = report["weighted avg"];

  const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;

  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table
        aria-label="Per-class classification report"
        className="min-w-full text-sm"
      >
        <caption className="sr-only">
          Per-class precision, recall, F1, and support values from the held-out
          evaluation set.
        </caption>
        <thead className="bg-muted">
          <tr>
            <th className="px-4 py-2 text-left font-semibold text-muted-foreground">
              Class
            </th>
            <th className="px-4 py-2 text-right font-semibold text-muted-foreground">
              Precision
            </th>
            <th className="px-4 py-2 text-right font-semibold text-muted-foreground">
              Recall
            </th>
            <th className="px-4 py-2 text-right font-semibold text-muted-foreground">
              F1
            </th>
            <th className="px-4 py-2 text-right font-semibold text-muted-foreground">
              Support
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {classRows.map(([label, row]) =>
            isClassReportRow(row) ? (
              <tr key={label}>
                <td
                  className="max-w-[8rem] overflow-hidden text-ellipsis whitespace-nowrap px-4 py-2 font-medium text-foreground"
                  title={label}
                >
                  {label}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {fmtPct(row.precision)}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {fmtPct(row.recall)}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {fmtPct(row["f1-score"])}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">{row.support}</td>
              </tr>
            ) : null,
          )}
        </tbody>
        {isClassReportRow(macroAvg) || isClassReportRow(weightedAvg) ? (
          <tfoot className="border-t-2 border-border bg-muted/50">
            {isClassReportRow(macroAvg) ? (
              <tr>
                <td className="px-4 py-2 font-semibold">Macro avg</td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {fmtPct(macroAvg.precision)}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {fmtPct(macroAvg.recall)}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {fmtPct(macroAvg["f1-score"])}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {macroAvg.support}
                </td>
              </tr>
            ) : null}
            {isClassReportRow(weightedAvg) ? (
              <tr>
                <td className="px-4 py-2 font-semibold">Weighted avg</td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {fmtPct(weightedAvg.precision)}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {fmtPct(weightedAvg.recall)}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {fmtPct(weightedAvg["f1-score"])}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {weightedAvg.support}
                </td>
              </tr>
            ) : null}
          </tfoot>
        ) : null}
      </table>
    </div>
  );
}

function ClassDistributionChart({
  items,
}: {
  items: readonly { label: string; count: number }[];
}): ReactElement {
  const total = items.reduce((s, i) => s + i.count, 0);
  const max = Math.max(...items.map((i) => i.count), 1);

  return (
    <div role="list" aria-label="Class distribution">
      <div className="space-y-2">
        {items.map((item) => {
          const pct = total > 0 ? (item.count / total) * 100 : 0;
          const barPct = (item.count / max) * 100;
          return (
            <div
              className="flex items-center gap-2 text-xs"
              key={item.label}
              role="listitem"
              aria-label={`${item.label}: ${item.count} (${pct.toFixed(1)}%)`}
            >
              <span
                className="w-20 shrink-0 overflow-hidden text-ellipsis whitespace-nowrap text-right text-muted-foreground"
                title={item.label}
              >
                {item.label}
              </span>
              <div
                className="flex-1 rounded-sm bg-muted/30"
                style={{ height: "1.25rem" }}
              >
                <div
                  className="h-full rounded-sm bg-primary/70"
                  style={{ width: `${barPct}%` }}
                  aria-hidden="true"
                />
              </div>
              <span className="w-28 shrink-0 tabular-nums text-muted-foreground">
                {item.count} ({pct.toFixed(1)}%)
              </span>
            </div>
          );
        })}
      </div>
      <p className="sr-only">
        Total: {total} samples across {items.length} classes.
      </p>
    </div>
  );
}

function ExplainabilityCapabilityPanel({
  evaluation,
}: {
  evaluation: EvaluationPayload;
}): ReactElement {
  const explainability = evaluation.explainability ?? {};
  const plots = evaluation.plots ?? {};
  const omitted = {
    ...(evaluation.omitted_metrics ?? {}),
    ...(evaluation.omitted ?? {}),
  };

  const items: { label: string; supported: boolean; reason?: string }[] = [
    {
      label: "Global explanation",
      supported:
        isRankedFeatureList(explainability.native_feature_importance) ||
        isRankedFeatureList(explainability.coefficients) ||
        isRankedFeatureList(explainability.permutation_importance),
    },
    {
      label: "Local explanation",
      supported: false,
      reason: explainability.local?.reason ?? "Not available.",
    },
    {
      label: "Probabilities",
      supported:
        plots.roc_curve !== undefined ||
        plots.calibration !== undefined ||
        plots.probability_distribution !== undefined,
      reason: omitted["roc_auc"],
    },
    {
      label: "Feature importance",
      supported: isRankedFeatureList(explainability.native_feature_importance),
    },
    {
      label: "Coefficients",
      supported: isRankedFeatureList(explainability.coefficients),
    },
    {
      label: "Permutation importance",
      supported: isRankedFeatureList(explainability.permutation_importance),
    },
  ];

  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <h3 className="text-base font-semibold text-foreground">
        Explanation capabilities
      </h3>
      <ul className="mt-3 space-y-2" role="list">
        {items.map((item) => (
          <li
            className="flex items-start gap-2 text-sm"
            key={item.label}
            role="listitem"
          >
            <span
              aria-label={item.supported ? "Supported" : "Not supported"}
              className={`mt-0.5 shrink-0 text-base ${
                item.supported ? "text-success-600" : "text-muted-foreground/50"
              }`}
            >
              {item.supported ? "✓" : "✗"}
            </span>
            <span>
              <span className="font-medium text-foreground">{item.label}</span>
              {!item.supported && item.reason ? (
                <span className="ml-1 text-muted-foreground">— {item.reason}</span>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
      {explainability.notice ? (
        <p className="mt-4 text-xs italic text-muted-foreground">
          ⚠ {explainability.notice}
        </p>
      ) : (
        <p className="mt-4 text-xs italic text-muted-foreground">
          ⚠ Model explanations describe model behavior and are not causal conclusions.
        </p>
      )}
    </div>
  );
}

// ─── Metric metadata ──────────────────────────────────────────────────────────

const CLASSIFICATION_METRIC_ORDER = [
  { key: "accuracy", label: "Accuracy", direction: "higher-better" as const },
  { key: "f1_macro", label: "F1 Macro", direction: "higher-better" as const },
  { key: "f1_weighted", label: "F1 Weighted", direction: "higher-better" as const },
  {
    key: "precision_macro",
    label: "Precision Macro",
    direction: "higher-better" as const,
  },
  {
    key: "precision_weighted",
    label: "Precision Weighted",
    direction: "higher-better" as const,
  },
  { key: "recall_macro", label: "Recall Macro", direction: "higher-better" as const },
  {
    key: "recall_weighted",
    label: "Recall Weighted",
    direction: "higher-better" as const,
  },
  { key: "roc_auc", label: "ROC AUC", direction: "higher-better" as const },
  { key: "log_loss", label: "Log Loss", direction: "lower-better" as const },
];

const REGRESSION_METRIC_ORDER = [
  { key: "r2", label: "R²", direction: "higher-better" as const },
  { key: "mae", label: "MAE", direction: "lower-better" as const },
  { key: "rmse", label: "RMSE", direction: "lower-better" as const },
  { key: "mse", label: "MSE", direction: "lower-better" as const },
  {
    key: "median_absolute_error",
    label: "Median Abs Error",
    direction: "lower-better" as const,
  },
  { key: "mape", label: "MAPE", direction: "lower-better" as const },
];

// ─── Main page ────────────────────────────────────────────────────────────────

export function TrainingEvaluationPage(): ReactElement {
  const { trainingJobId = "" } = useParams();
  const [data, setData] = useState<{
    job: TrainingJob;
    evaluation: EvaluationPayload;
  } | null>(null);
  const [error, setError] = useState<{
    trainingJobId: string;
    message: string;
  } | null>(null);
  const [activeTab, setActiveTab] = useState<
    "overview" | "plots" | "explainability" | "config"
  >("overview");

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getTrainingJob(trainingJobId, controller.signal),
      getTrainingEvaluation(trainingJobId, controller.signal),
    ])
      .then(([job, evaluation]) => {
        if (!controller.signal.aborted) setData({ job, evaluation });
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted)
          setError({
            trainingJobId,
            message:
              caught instanceof Error
                ? caught.message
                : "Unable to load this evaluation.",
          });
      });
    return () => controller.abort();
  }, [trainingJobId]);

  if (error?.trainingJobId === trainingJobId)
    return (
      <InlineError message={error.message} onRetry={() => window.location.reload()} />
    );
  if (!data || data.job.job_id !== trainingJobId)
    return <LoadingSkeleton label="Loading held-out evaluation" />;

  const { evaluation, job } = data;
  const metrics = evaluation.metrics ?? {};
  const plots = evaluation.plots ?? {};
  const omitted = {
    ...(evaluation.omitted_metrics ?? {}),
    ...(evaluation.omitted ?? {}),
  };
  const explainability = evaluation.explainability ?? {};
  const isClassification = evaluation.task_type === "classification";
  const isRegression = evaluation.task_type === "regression";

  const metricOrder = isClassification
    ? CLASSIFICATION_METRIC_ORDER
    : REGRESSION_METRIC_ORDER;

  const tabs = [
    { id: "overview" as const, label: "Overview" },
    {
      id: "plots" as const,
      label: isClassification ? "Classification plots" : "Regression plots",
    },
    { id: "explainability" as const, label: "Explainability" },
    { id: "config" as const, label: "Configuration" },
  ];

  return (
    <div className="space-y-6">
      {/* ── Header ────────────────────────────────────────────────────── */}
      <div>
        <Link
          className="mb-4 inline-block text-sm font-medium text-primary hover:underline"
          to="/evaluations"
        >
          ← Evaluation Studio
        </Link>
        <PageHeader
          eyebrow="Evaluation Studio"
          headingId="training-evaluation-heading"
          title={`${job.registered_model_name} v${job.registered_model_version ?? "—"}`}
          description={
            <span className="flex flex-wrap items-center gap-2">
              <BadgePill variant={isClassification ? "classification" : "regression"}>
                {evaluation.task_type}
              </BadgePill>
              <BadgePill>{evaluation.algorithm.replaceAll("_", " ")}</BadgePill>
              <BadgePill>
                {evaluation.sample_count.toLocaleString()} held-out samples
              </BadgePill>
              <BadgePill>{evaluation.feature_count} features</BadgePill>
            </span>
          }
        />
      </div>

      {/* ── Metric cards ──────────────────────────────────────────────── */}
      <section aria-label="Held-out metrics">
        <h2 className="sr-only">Held-out metrics</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {metricOrder.map(({ key, label, direction }) => {
            const value = metrics[key];
            const omittedReason = omitted[key];
            return (
              <MetricCard
                key={key}
                label={label}
                value={value}
                direction={direction}
                omittedReason={omittedReason}
              />
            );
          })}
        </div>
      </section>

      {/* ── Tabs ──────────────────────────────────────────────────────── */}
      <div className="border-b border-border">
        <nav
          aria-label="Evaluation sections"
          className="-mb-px flex gap-1 overflow-x-auto"
          role="tablist"
        >
          {tabs.map((tab) => (
            <button
              key={tab.id}
              aria-current={activeTab === tab.id ? "page" : undefined}
              aria-selected={activeTab === tab.id}
              className={`shrink-0 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                activeTab === tab.id
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:border-border hover:text-foreground"
              }`}
              onClick={() => setActiveTab(tab.id)}
              role="tab"
              type="button"
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* ── Tab: Overview ─────────────────────────────────────────────── */}
      {activeTab === "overview" ? (
        <div className="space-y-6" role="tabpanel" aria-label="Overview">
          {/* Model info */}
          <section
            aria-label="Model summary"
            className="rounded-lg border border-border bg-card p-5"
          >
            <h2 className="text-base font-semibold text-foreground">
              Model information
            </h2>
            <dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-sm">
              {[
                ["Name", job.registered_model_name],
                ["Version", job.registered_model_version ?? "—"],
                ["Task", evaluation.task_type],
                ["Algorithm", evaluation.algorithm.replaceAll("_", " ")],
                ["Held-out samples", evaluation.sample_count.toLocaleString()],
                ["Features", evaluation.feature_count.toString()],
                ["Schema version", evaluation.schema_version],
                ["Job ID", job.job_id.slice(0, 8) + "…"],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {label}
                  </dt>
                  <dd className="mt-0.5 font-medium text-foreground">{value}</dd>
                </div>
              ))}
            </dl>
          </section>

          {/* All metrics table */}
          <section
            aria-label="All metrics"
            className="rounded-lg border border-border bg-card p-5"
          >
            <h2 className="text-base font-semibold text-foreground">
              All held-out metrics
            </h2>
            <div className="mt-3 overflow-x-auto">
              <table className="min-w-full text-sm" aria-label="Evaluation metrics">
                <thead className="bg-muted">
                  <tr>
                    <th className="px-4 py-2 text-left font-semibold text-muted-foreground">
                      Metric
                    </th>
                    <th className="px-4 py-2 text-right font-semibold text-muted-foreground">
                      Value
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {Object.entries(metrics).map(([name, value]) => (
                    <tr key={name}>
                      <td className="px-4 py-2 text-foreground">
                        {name.replaceAll("_", " ")}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-foreground">
                        {value.toFixed(6)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* Omitted metrics */}
          {Object.keys(omitted).length > 0 ? (
            <section
              aria-label="Omitted or unavailable metrics"
              className="rounded-lg border border-warning-200 bg-warning-50 p-5 dark:border-warning-800/50 dark:bg-warning-900/20"
            >
              <h2 className="font-semibold text-warning-900 dark:text-warning-200">
                Omitted metrics and plots
              </h2>
              <ul className="mt-2 space-y-1 text-sm text-warning-800 dark:text-warning-300">
                {Object.entries(omitted).map(([name, reason]) => (
                  <li key={name}>
                    <strong className="font-medium">
                      {name.replaceAll("_", " ")}:
                    </strong>{" "}
                    {reason}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      ) : null}

      {/* ── Tab: Classification plots ──────────────────────────────────── */}
      {activeTab === "plots" && isClassification ? (
        <div className="space-y-6" role="tabpanel" aria-label="Classification plots">
          {/* Confusion matrix */}
          <ChartPanel
            title="Confusion matrix"
            description="Rows = actual class · Columns = predicted class · Diagonal = correct predictions"
            isUnsupported={!plots.confusion_matrix}
            unsupportedReason="Confusion matrix data was not returned."
          >
            {plots.confusion_matrix ? (
              <ConfusionMatrix
                data={plots.confusion_matrix}
                aria-label="Confusion matrix heatmap"
              />
            ) : null}
          </ChartPanel>

          {/* Class distribution */}
          <ChartPanel
            title="Class distribution"
            description="Count of held-out samples per class label"
            isUnsupported={!plots.class_distribution}
            unsupportedReason="Class distribution data was not returned."
          >
            {plots.class_distribution ? (
              <ClassDistributionChart items={plots.class_distribution} />
            ) : null}
          </ChartPanel>

          {/* ROC curve */}
          <ChartPanel
            title="ROC curve"
            description="Receiver operating characteristic. Binary classifiers only. Dashed line = random chance."
            isUnsupported={!plots.roc_curve || omitted.roc_curve !== undefined}
            unsupportedReason={omitted.roc_curve ?? "ROC curve data is not available."}
          >
            {plots.roc_curve ? (
              <LineSeriesChart
                aria-label="ROC curve"
                showDiagonal={true}
                xLabel="False positive rate"
                yLabel="True positive rate"
                xUnit={true}
                yUnit={true}
                summary={`AUC: ${metrics["roc_auc"]?.toFixed(4) ?? "—"}`}
                series={[
                  {
                    label: `ROC (AUC = ${metrics["roc_auc"]?.toFixed(4) ?? "—"})`,
                    points: plots.roc_curve.map((p) => ({
                      x: p.x,
                      y: p.y,
                    })),
                    color: "#6d4aff",
                  },
                  {
                    label: "Random chance",
                    points: [
                      { x: 0, y: 0 },
                      { x: 1, y: 1 },
                    ],
                    color: "#8e8ba0",
                    dashed: true,
                  },
                ]}
              />
            ) : null}
          </ChartPanel>

          {/* Precision-recall curve */}
          <ChartPanel
            title="Precision-recall curve"
            description="Binary classifiers only."
            isUnsupported={
              !plots.precision_recall_curve ||
              omitted.precision_recall_curve !== undefined
            }
            unsupportedReason={
              omitted.precision_recall_curve ??
              "Precision-recall data is not available."
            }
          >
            {plots.precision_recall_curve ? (
              <LineSeriesChart
                aria-label="Precision-recall curve"
                xLabel="Recall"
                yLabel="Precision"
                xUnit={true}
                yUnit={true}
                series={[
                  {
                    label: "Precision-recall",
                    points: plots.precision_recall_curve.map((p) => ({
                      x: p.x,
                      y: p.y,
                    })),
                    color: "#e04f56",
                  },
                ]}
              />
            ) : null}
          </ChartPanel>

          {/* Calibration curve */}
          <ChartPanel
            title="Calibration curve"
            description="Predicted probability vs. observed frequency. Perfect calibration = diagonal."
            isUnsupported={!plots.calibration || omitted.calibration !== undefined}
            unsupportedReason={
              omitted.calibration ?? "Calibration data is not available."
            }
          >
            {plots.calibration ? (
              <LineSeriesChart
                aria-label="Calibration curve"
                showDiagonal={true}
                xLabel="Mean predicted probability"
                yLabel="Fraction of positives"
                xUnit={true}
                yUnit={true}
                series={[
                  {
                    label: "Model calibration",
                    points: plots.calibration.map((p) => ({
                      x: p.x,
                      y: p.y,
                    })),
                    color: "#198754",
                  },
                  {
                    label: "Perfect calibration",
                    points: [
                      { x: 0, y: 0 },
                      { x: 1, y: 1 },
                    ],
                    color: "#8e8ba0",
                    dashed: true,
                  },
                ]}
              />
            ) : null}
          </ChartPanel>

          {/* Probability distribution */}
          <ChartPanel
            title="Probability distribution"
            description="Histogram of predicted positive-class probabilities (binary models only)."
            isUnsupported={
              !plots.probability_distribution || omitted.roc_auc !== undefined
            }
            unsupportedReason={
              omitted.roc_auc ?? "Probability distribution is not available."
            }
          >
            {plots.probability_distribution ? (
              <HistogramChart
                aria-label="Probability distribution histogram"
                bins={plots.probability_distribution}
                xLabel="Predicted probability"
                yLabel="Count"
              />
            ) : null}
          </ChartPanel>

          {/* Classification report */}
          {evaluation.classification_report ? (
            <ChartPanel
              title="Classification report"
              description="Per-class precision, recall, F1, and support from the held-out set."
            >
              <ClassificationReportTable report={evaluation.classification_report} />
            </ChartPanel>
          ) : null}
        </div>
      ) : null}

      {/* ── Tab: Regression plots ────────────────────────────────────── */}
      {activeTab === "plots" && isRegression ? (
        <div className="space-y-6" role="tabpanel" aria-label="Regression plots">
          {/* Actual vs predicted */}
          <ChartPanel
            title="Actual vs predicted"
            description="Dashed diagonal = perfect predictions. Points are bounded held-out samples."
            isUnsupported={!plots.actual_vs_predicted}
            unsupportedReason="Actual vs predicted data was not returned."
          >
            {plots.actual_vs_predicted ? (
              <ScatterChart
                aria-label="Actual vs predicted scatter plot"
                showIdentityLine={true}
                xLabel="Actual"
                yLabel="Predicted"
                points={plots.actual_vs_predicted.map((p) => ({
                  x: p.actual,
                  y: p.predicted,
                }))}
                summary={`${plots.actual_vs_predicted.length} bounded held-out points.`}
              />
            ) : null}
          </ChartPanel>

          {/* Residual plot */}
          <ChartPanel
            title="Residual plot"
            description="Residual = actual − predicted. Dashed line = zero residual."
            isUnsupported={!plots.residuals}
            unsupportedReason="Residual data was not returned."
          >
            {plots.residuals ? (
              <ScatterChart
                aria-label="Residual scatter plot"
                showZeroLine={true}
                xLabel="Predicted value"
                yLabel="Residual"
                points={plots.residuals.map((p) => ({
                  x: p.predicted,
                  y: p.residual,
                }))}
              />
            ) : null}
          </ChartPanel>

          {/* Residual distribution */}
          <ChartPanel
            title="Residual distribution"
            description="Distribution of residuals. Dashed line = zero. No interpretation is fabricated."
            isUnsupported={!plots.residual_distribution}
            unsupportedReason="Residual distribution data was not returned."
          >
            {plots.residual_distribution ? (
              <HistogramChart
                aria-label="Residual distribution histogram"
                bins={plots.residual_distribution}
                xLabel="Residual"
                yLabel="Count"
                showZeroReference={true}
              />
            ) : null}
          </ChartPanel>

          {/* Absolute error distribution */}
          <ChartPanel
            title="Absolute error distribution"
            description="Distribution of per-sample absolute prediction errors."
            isUnsupported={!plots.absolute_error_distribution}
            unsupportedReason="Absolute error distribution data was not returned."
          >
            {plots.absolute_error_distribution ? (
              <HistogramChart
                aria-label="Absolute error distribution histogram"
                bins={plots.absolute_error_distribution}
                xLabel="Absolute error"
                yLabel="Count"
                barColor="#e04f56"
              />
            ) : null}
          </ChartPanel>

          {/* Error by prediction range */}
          <ChartPanel
            title="Error by prediction range"
            description="Mean absolute error per prediction bucket. Only non-empty buckets are shown."
            isUnsupported={!plots.error_by_prediction_range}
            unsupportedReason="Error by range data was not returned."
          >
            {plots.error_by_prediction_range ? (
              <HistogramChart
                aria-label="Mean absolute error by prediction range"
                bins={plots.error_by_prediction_range.map((b) => ({
                  start: b.start,
                  end: b.end,
                  count: Math.round(b.mean_absolute_error * 1000) / 1000,
                }))}
                xLabel="Prediction range"
                yLabel="Mean abs error"
                barColor="#f59e0b"
              />
            ) : null}
          </ChartPanel>
        </div>
      ) : null}

      {/* ── Tab: Explainability ────────────────────────────────────────── */}
      {activeTab === "explainability" ? (
        <div className="space-y-6" role="tabpanel" aria-label="Explainability">
          <ExplainabilityCapabilityPanel evaluation={evaluation} />

          <SectionDivider title="Global feature explanations" />

          {/* Feature importance */}
          <ChartPanel
            title="Native feature importance"
            description="Ranked by absolute importance. Source: model-native importance attribute (e.g., Random Forest impurity)."
            isUnsupported={
              !isRankedFeatureList(explainability.native_feature_importance)
            }
            unsupportedReason={
              !isRankedFeatureList(explainability.native_feature_importance)
                ? explainabilityReason(explainability.native_feature_importance)
                : ""
            }
          >
            {isRankedFeatureList(explainability.native_feature_importance) ? (
              <HorizontalBarChart
                aria-label="Native feature importance"
                items={explainability.native_feature_importance}
                sourceNote="Native importance from model internals. Not a causal measure."
                maxItems={30}
              />
            ) : null}
          </ChartPanel>

          {/* Coefficients */}
          <ChartPanel
            title="Model coefficients"
            description="Linear model coefficient magnitude. Positive = increases prediction. Negative = decreases prediction."
            isUnsupported={!isRankedFeatureList(explainability.coefficients)}
            unsupportedReason={
              !isRankedFeatureList(explainability.coefficients)
                ? explainabilityReason(explainability.coefficients)
                : ""
            }
          >
            {isRankedFeatureList(explainability.coefficients) ? (
              <HorizontalBarChart
                aria-label="Model coefficients"
                items={explainability.coefficients}
                showZeroLine={true}
                sourceNote="Coefficients from a linear model. Not a causal measure."
              />
            ) : null}
          </ChartPanel>

          {/* Permutation importance */}
          <ChartPanel
            title="Permutation importance"
            description="Mean decrease in score when each feature is randomly shuffled. Computed on bounded held-out sample."
            isUnsupported={!isRankedFeatureList(explainability.permutation_importance)}
            unsupportedReason={
              !isRankedFeatureList(explainability.permutation_importance)
                ? explainabilityReason(explainability.permutation_importance)
                : ""
            }
          >
            {isRankedFeatureList(explainability.permutation_importance) ? (
              <HorizontalBarChart
                aria-label="Permutation importance"
                items={explainability.permutation_importance}
                sourceNote="Permutation importance. Captures model-dependency, not data causality."
                maxItems={30}
              />
            ) : null}
          </ChartPanel>

          {/* Local explanation — always unsupported */}
          <ChartPanel
            title="Local explanations"
            isUnsupported={true}
            unsupportedReason={
              explainability.local?.reason ??
              "Local contribution explanations are not available for this algorithm."
            }
          >
            {null}
          </ChartPanel>

          <p className="text-xs italic text-muted-foreground">
            {explainability.notice ??
              "Model explanations describe model behavior and are not causal conclusions. Local explanations and SHAP are not available in this milestone."}
          </p>
        </div>
      ) : null}

      {/* ── Tab: Configuration ────────────────────────────────────────── */}
      {activeTab === "config" ? (
        <div className="space-y-4" role="tabpanel" aria-label="Configuration">
          <section
            aria-label="Training job metadata"
            className="rounded-lg border border-border bg-card p-5"
          >
            <h2 className="text-base font-semibold text-foreground">Training job</h2>
            <dl className="mt-3 grid gap-3 sm:grid-cols-2 text-sm">
              {[
                ["Job ID", job.job_id],
                ["Status", job.status],
                ["Algorithm", evaluation.algorithm],
                ["Task", evaluation.task_type],
                ["Created", new Date(job.created_at).toLocaleString()],
                [
                  "Finished",
                  job.finished_at ? new Date(job.finished_at).toLocaleString() : "—",
                ],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {label}
                  </dt>
                  <dd className="mt-0.5 break-all font-medium text-foreground">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        </div>
      ) : null}
    </div>
  );
}
