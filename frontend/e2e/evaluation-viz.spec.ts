import { expect, test, type Page, type Route } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

async function mockAuthenticatedUser(page: Page): Promise<void> {
  await page.addInitScript(
    ({ expiresAt }) => {
      sessionStorage.setItem(
        "factorymind.auth.tokens",
        JSON.stringify({
          accessToken: "browser-test-access-token",
          accessTokenExpiresAt: expiresAt,
          refreshToken: "browser-test-refresh-token",
        }),
      );
    },
    { expiresAt: Date.now() + 3_600_000 },
  );
  await page.route("**/users/me", (route) =>
    json(route, {
      created_at: "2026-01-01T00:00:00Z",
      email: "engineer@e2e.example.local",
      id: "e2e-engineer",
      is_active: true,
      role: "engineer",
      updated_at: "2026-01-01T00:00:00Z",
    }),
  );
}

const mockJob = {
  job_id: "job-123",
  requested_by_user_id: "e2e-engineer",
  trainer_key: { algorithm: "random_forest", task_type: "classification" },
  status: "succeeded",
  created_at: "2026-01-01T00:00:00Z",
  queued_at: "2026-01-01T00:00:00Z",
  started_at: "2026-01-01T00:00:01Z",
  finished_at: "2026-01-01T00:01:00Z",
  cancelled_at: null,
  attempt_count: 1,
  max_attempts: 3,
  metrics: null,
  local_execution_run_id: null,
  mlflow_experiment_id: null,
  mlflow_run_id: null,
  registered_model_name: "test_model",
  registered_model_version: null,
  error_code: null,
  safe_error_message: null,
};

const mockClassificationEvaluation = {
  schema_version: "1.0",
  task_type: "classification",
  algorithm: "random_forest",
  sample_count: 100,
  feature_count: 5,
  metrics: {
    accuracy: 0.95,
    f1_macro: 0.94,
    precision_macro: 0.96,
    recall_macro: 0.93,
  },
  plots: {
    confusion_matrix: {
      labels: ["Class 0", "Class 1"],
      values: [
        [45, 5],
        [2, 48],
      ],
    },
  },
  explainability: {
    native_feature_importance: [
      { feature: "sensor_1", value: 0.6 },
      { feature: "sensor_2", value: 0.4 },
    ],
  },
  omitted: {},
  classification_report: {
    "Class 0": { precision: 0.95, recall: 0.9, "f1-score": 0.92, support: 50 },
    "Class 1": { precision: 0.9, recall: 0.96, "f1-score": 0.93, support: 50 },
  },
};

const mockRegressionEvaluation = {
  schema_version: "1.0",
  task_type: "regression",
  algorithm: "linear_regression",
  sample_count: 100,
  feature_count: 5,
  metrics: {
    rmse: 1.5,
    mae: 1.2,
    r2: 0.88,
  },
  plots: {
    actual_vs_predicted: [
      { actual: 1.0, predicted: 1.1 },
      { actual: 2.0, predicted: 1.9 },
    ],
    residuals: [
      { predicted: 1.1, residual: -0.1 },
      { predicted: 1.9, residual: 0.1 },
    ],
  },
  explainability: {
    coefficients: [
      { feature: "sensor_1", value: 1.5 },
      { feature: "sensor_2", value: -0.5 },
    ],
  },
  omitted: {},
};

test.describe("Evaluation Visualizations", () => {
  test("renders classification plots and metrics", async ({ page }) => {
    await mockAuthenticatedUser(page);

    await page.route("**/ai/training-jobs/job-123", (route) => json(route, mockJob));
    await page.route("**/ai/training-jobs/job-123/evaluation", (route) =>
      json(route, mockClassificationEvaluation),
    );

    await page.goto("/evaluations/jobs/job-123");

    // Wait for the loading to finish
    await expect(
      page.getByRole("heading", { name: "All held-out metrics" }),
    ).toBeVisible();

    // Check Metrics Cards
    await expect(page.getByText("Accuracy").first()).toBeVisible();
    await expect(page.getByText("0.95").first()).toBeVisible();

    // Check tabs
    await expect(page.getByRole("tab", { name: "Classification plots" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Explainability" })).toBeVisible();
    const axe = await new AxeBuilder({ page }).analyze();
    expect(
      axe.violations.filter(
        ({ impact }) => impact === "critical" || impact === "serious",
      ),
    ).toEqual([]);

    // Plots tab (needs click first)
    await page.getByRole("tab", { name: "Classification plots" }).click();
    await expect(page.getByText("Confusion matrix").first()).toBeVisible();

    // Switch to Explainability tab
    await page.getByRole("tab", { name: "Explainability" }).click();
    await expect(page.getByText("Feature importance").first()).toBeVisible();
    await expect(page.getByText("sensor_1").first()).toBeVisible();
  });

  test("renders regression plots and metrics", async ({ page }) => {
    await mockAuthenticatedUser(page);

    const regJob = {
      ...mockJob,
      trainer_key: { algorithm: "linear_regression", task_type: "regression" },
    };
    await page.route("**/ai/training-jobs/job-123", (route) => json(route, regJob));
    await page.route("**/ai/training-jobs/job-123/evaluation", (route) =>
      json(route, mockRegressionEvaluation),
    );

    await page.goto("/evaluations/jobs/job-123");

    // Wait for metrics
    await expect(
      page.getByRole("heading", { name: "All held-out metrics" }),
    ).toBeVisible();
    await expect(page.getByText("RMSE").first()).toBeVisible();
    await expect(page.getByText("1.5").first()).toBeVisible();

    // Regression Plots
    await page.getByRole("tab", { name: "Regression plots" }).click();
    await expect(page.getByText("Actual vs predicted").first()).toBeVisible();

    // Explainability
    await page.getByRole("tab", { name: "Explainability" }).click();
    await expect(page.getByText("Model coefficients").first()).toBeVisible();
    await expect(page.getByText("sensor_2").first()).toBeVisible();
  });

  test("renders legacy evaluation payloads without optional visualization data", async ({
    page,
  }) => {
    await mockAuthenticatedUser(page);

    await page.route("**/ai/training-jobs/job-123", (route) => json(route, mockJob));
    await page.route("**/ai/training-jobs/job-123/evaluation", (route) =>
      json(route, {
        algorithm: "random_forest",
        feature_count: 5,
        metrics: { accuracy: 0.91 },
        omitted_metrics: { roc_auc: "Probability scores were not available." },
        sample_count: 20,
        schema_version: "0.1",
        task_type: "classification",
      }),
    );

    await page.goto("/evaluations/jobs/job-123");

    await expect(page.getByText("0.91").first()).toBeVisible();
    await expect(
      page.getByRole("tablist", { name: "Evaluation sections" }),
    ).toBeVisible();
    await page.getByRole("tab", { name: "Classification plots" }).click();
    await expect(
      page.getByText("Confusion matrix data was not returned."),
    ).toBeVisible();
    await expect(
      page.getByText("Probability scores were not available."),
    ).toBeVisible();
    await page.getByRole("tab", { name: "Explainability" }).click();
    await expect(page.getByText("Not available.").first()).toBeVisible();
  });
});
