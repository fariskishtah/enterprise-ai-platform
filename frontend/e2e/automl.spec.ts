import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const NOW = "2026-07-22T10:00:00Z";
const STUDY_ID = "11111111-1111-4111-8111-111111111111";
const TRIAL_ID = "22222222-2222-4222-8222-222222222222";

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function collectUnexpectedBrowserErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

async function authenticated(
  page: Page,
  role: "engineer" | "operator" = "engineer",
): Promise<void> {
  await page.addInitScript(
    ({ expiresAt }) =>
      sessionStorage.setItem(
        "factorymind.auth.tokens",
        JSON.stringify({
          accessToken: "automl-access",
          accessTokenExpiresAt: expiresAt,
          refreshToken: "automl-refresh",
        }),
      ),
    { expiresAt: Date.now() + 3_600_000 },
  );
  await page.route("**/users/me", (route) =>
    json(route, {
      created_at: NOW,
      email: `${role}@example.local`,
      id: `${role}-id`,
      is_active: true,
      role,
      updated_at: NOW,
    }),
  );
}

function study(status: string) {
  return {
    best_trial_id: status === "succeeded" ? TRIAL_ID : null,
    cancel_requested_at: null,
    champion_training_job_id: null,
    created_at: NOW,
    cross_validation_folds: 2,
    data_specification: {
      evaluation_row_count: 2,
      feature_count: 1,
      training_row_count: 6,
    },
    finished_at: status === "succeeded" ? NOW : null,
    max_concurrent_trials: 1,
    metric_direction: "minimize",
    per_trial_timeout_seconds: 60,
    plugin_ids: ["ridge_regression"],
    preprocessing: { imputer: "none", scaler: "standard" },
    primary_metric: "rmse",
    random_seed: 17,
    register_champion: false,
    registered_model_name: null,
    requested_by_user_id: "engineer-id",
    safe_error_message: null,
    sampler_type: "random",
    search_spaces: [],
    started_at: NOW,
    status,
    study_id: STUDY_ID,
    task_type: "regression",
    time_budget_seconds: 300,
    trial_budget: 2,
  };
}

const trial = {
  aggregate_metrics: { rmse_mean: 0.1, rmse_std: 0.01 },
  attempt_count: 1,
  created_at: NOW,
  duration_seconds: 0.5,
  finished_at: NOW,
  fold_metrics: [{ rmse: 0.09 }, { rmse: 0.11 }],
  max_attempts: 3,
  parameters: { alpha: 1 },
  plugin_id: "ridge_regression",
  primary_metric_value: 0.1,
  safe_error_message: null,
  started_at: NOW,
  status: "succeeded",
  study_id: STUDY_ID,
  trial_id: TRIAL_ID,
  trial_number: 0,
};
const leaderboard = [
  {
    duration_seconds: 0.5,
    metric_standard_deviation: 0.01,
    parameters: { alpha: 1 },
    plugin_id: "ridge_regression",
    primary_metric_value: 0.1,
    rank: 1,
    status: "succeeded",
    trial_id: TRIAL_ID,
    trial_number: 0,
  },
];

async function mockStudy(page: Page, status = "succeeded"): Promise<void> {
  await page.route(`**/ai/automl/studies/${STUDY_ID}/leaderboard`, (route) =>
    json(route, leaderboard),
  );
  await page.route(`**/ai/automl/studies/${STUDY_ID}/trials**`, (route) =>
    json(route, { items: [trial], limit: 20, offset: 0, total: 1 }),
  );
  await page.route(`**/ai/automl/studies/${STUDY_ID}/trials/${TRIAL_ID}`, (route) =>
    json(route, trial),
  );
  await page.route(`**/ai/automl/studies/${STUDY_ID}`, (route) =>
    json(route, study(status)),
  );
}

test("AutoML navigation, empty list, role authorization, and accessibility", async ({
  page,
}) => {
  const errors = collectUnexpectedBrowserErrors(page);
  await authenticated(page);
  await page.route("**/ai/automl/studies**", (route) =>
    json(route, { items: [], limit: 20, offset: 0, total: 0 }),
  );
  await page.goto("/automl");
  await expect(page.locator("#automl-heading")).toBeVisible();
  await expect(page.getByText("No AutoML studies")).toBeVisible();
  expect(
    (await new AxeBuilder({ page }).analyze()).violations.filter(
      ({ impact }) => impact === "critical" || impact === "serious",
    ),
  ).toEqual([]);

  const operator = await page.context().newPage();
  await authenticated(operator, "operator");
  await operator.goto("/automl");
  await expect(operator).toHaveURL(/\/$/);
  await operator.close();
  expect(errors).toEqual([]);
});

test("creation validates compatibility, prevents duplicate submit, and redirects", async ({
  page,
}) => {
  const errors = collectUnexpectedBrowserErrors(page);
  await authenticated(page);
  await page.route("**/ai/automl/algorithms", (route) =>
    json(route, [
      {
        display_name: "Ridge Regression",
        id: "ridge_regression",
        parameters: [
          {
            choices: [],
            default: 1,
            high: 10,
            kind: "float",
            log_scale: false,
            low: 0.1,
            name: "alpha",
            step: 0.1,
          },
        ],
        probability_support: false,
        task_type: "regression",
      },
    ]),
  );
  let creates = 0;
  await page.route("**/ai/automl/studies", async (route) => {
    if (route.request().method() === "POST") {
      creates += 1;
      expect(route.request().headers()["idempotency-key"]).toBeTruthy();
      await json(
        route,
        {
          created: true,
          status: "queued",
          status_url: `/ai/automl/studies/${STUDY_ID}`,
          study_id: STUDY_ID,
          submitted_at: NOW,
        },
        202,
      );
    } else await json(route, { items: [], limit: 20, offset: 0, total: 0 });
  });
  await mockStudy(page, "queued");
  await page.goto("/automl/new");
  await page.getByRole("button", { name: "Create and start study" }).click();
  await expect(page.getByRole("alert")).toContainText("at least two");
  await page.getByText("Ridge Regression").click();
  await page.getByLabel("Training features").fill("0\n1\n2\n3\n4\n5");
  await page.getByLabel("Training targets").fill("0,1,2,3,4,5");
  await page.getByLabel("Evaluation features").fill("0.5\n4.5");
  await page.getByLabel("Evaluation targets").fill("0.5,4.5");
  await page.getByRole("button", { name: "Create and start study" }).dblclick();
  await expect(page).toHaveURL(new RegExp(`/automl/studies/${STUDY_ID}$`));
  expect(creates).toBe(1);
  expect(errors).toEqual([]);
});

test("study lifecycle, leaderboard, cancellation, trial detail, theme, and responsive layout", async ({
  page,
}) => {
  const errors = collectUnexpectedBrowserErrors(page);
  await authenticated(page);
  await mockStudy(page, "running");
  await page.route(`**/ai/automl/studies/${STUDY_ID}/cancel`, (route) =>
    json(route, {
      cancel_requested_at: NOW,
      cancellation: "requested",
      cancelled_at: null,
      status: "running",
      study_id: STUDY_ID,
    }),
  );
  await page.goto(`/automl/studies/${STUDY_ID}`);
  await expect(page.locator("#automl-study-heading")).toBeVisible();
  await page.getByLabel("Color theme").selectOption("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByText("Running", { exact: true }).first()).toBeVisible();
  await page.getByRole("tab", { name: "Leaderboard" }).click();
  await expect(page.getByRole("link", { name: "Trial 0" })).toBeVisible();
  await page.getByRole("button", { name: "Cancel study" }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "Active work may take a short time",
  );
  await page.getByRole("button", { name: "Keep running" }).click();
  await page.setViewportSize({ height: 844, width: 390 });
  await expect(page.locator("body")).not.toHaveCSS("overflow-x", "scroll");
  await page.goto(`/automl/studies/${STUDY_ID}/trials/${TRIAL_ID}`);
  await expect(page.getByRole("heading", { name: "Trial 0" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Aggregate metrics" })).toBeVisible();
  expect(
    (await new AxeBuilder({ page }).analyze()).violations.filter(
      ({ impact }) => impact === "critical" || impact === "serious",
    ),
  ).toEqual([]);
  expect(errors).toEqual([]);
});

test("unknown study displays a safe local error", async ({ page }) => {
  await authenticated(page);
  await page.route("**/ai/automl/studies/missing/**", (route) =>
    json(route, { detail: "AutoML study not found." }, 404),
  );
  await page.route("**/ai/automl/studies/missing", (route) =>
    json(route, { detail: "AutoML study not found." }, 404),
  );
  await page.goto("/automl/studies/missing");
  await expect(page.getByRole("alert")).toContainText("AutoML study not found");
});
