import { expect, test, type Page, type Route } from "@playwright/test";

const NOW = "2026-07-22T10:00:00Z";
const DATASET_ID = "31111111-1111-4111-8111-111111111111";
const READY_VERSION_ID = "32222222-2222-4222-8222-222222222222";
const PROCESSING_VERSION_ID = "33333333-3333-4333-8333-333333333333";
const JOB_ID = "34444444-4444-4444-8444-444444444444";
const STUDY_ID = "35555555-5555-4555-8555-555555555555";

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

async function authenticated(page: Page): Promise<void> {
  await page.addInitScript(
    ({ expiresAt }) =>
      sessionStorage.setItem(
        "factorymind.auth.tokens",
        JSON.stringify({
          accessToken: "dataset-training-access",
          accessTokenExpiresAt: expiresAt,
          refreshToken: "dataset-training-refresh",
        }),
      ),
    { expiresAt: Date.now() + 3_600_000 },
  );
  await page.route("**/users/me", (route) =>
    json(route, {
      created_at: NOW,
      email: "engineer@example.local",
      id: "engineer-id",
      is_active: true,
      role: "engineer",
      updated_at: NOW,
    }),
  );
}

async function registeredDatasetRoutes(page: Page): Promise<void> {
  await page.route("**/ai/datasets?**", (route) =>
    json(route, {
      items: [
        {
          archived_at: null,
          created_at: NOW,
          current_version_id: READY_VERSION_ID,
          description: "Bounded training fixture",
          id: DATASET_ID,
          kind: "tabular",
          name: "Pump health training",
          owner_user_id: "engineer-id",
          state_version: 1,
          status: "active",
          updated_at: NOW,
        },
      ],
      limit: 100,
      offset: 0,
      total: 1,
    }),
  );
  await page.route(`**/ai/datasets/${DATASET_ID}/versions?**`, (route) =>
    json(route, {
      items: [
        version(READY_VERSION_ID, 1, "ready"),
        version(PROCESSING_VERSION_ID, 2, "processing"),
      ],
      limit: 100,
      offset: 0,
      total: 2,
    }),
  );
}

function version(id: string, versionNumber: number, status: string) {
  return {
    archived_at: null,
    chunk_count: null,
    column_count: 3,
    created_at: NOW,
    dataset_id: DATASET_ID,
    document_count: null,
    failed_at: null,
    id,
    media_type: "text/csv",
    original_filename: "pump-health.csv",
    processing_started_at: NOW,
    ready_at: status === "ready" ? NOW : null,
    row_count: 24,
    sha256_digest: "a".repeat(64),
    size_bytes: 512,
    source_type: "upload",
    status,
    version_number: versionNumber,
  };
}

const algorithm = {
  algorithm_family: "linear",
  decision_function_support: false,
  default_parameters: {},
  dependency_available: true,
  description: "Deterministic linear regression.",
  display_name: "Linear Regression",
  feature_importance_support: false,
  global_explainability: false,
  id: "linear_regression",
  local_explainability: false,
  parameters: [],
  permutation_importance_support: false,
  probability_support: false,
  scaling_behavior: "auto",
  supported_tasks: ["regression"],
};

test("manual training submits exactly one ready registered dataset version", async ({
  page,
}) => {
  await authenticated(page);
  await registeredDatasetRoutes(page);
  await page.route("**/ai/algorithms", (route) => json(route, [algorithm]));
  await page.route("**/ai/training-jobs?**", (route) =>
    json(route, { items: [], limit: 20, offset: 0, total: 0 }),
  );
  await page.route(`**/ai/training-jobs/${JOB_ID}`, (route) =>
    json(route, trainingJob()),
  );

  let creates = 0;
  let submitted: Record<string, unknown> | null = null;
  await page.route("**/ai/training-jobs", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    creates += 1;
    submitted = route.request().postDataJSON() as Record<string, unknown>;
    await json(
      route,
      {
        job_id: JOB_ID,
        status: "queued",
        status_url: `/ai/training-jobs/${JOB_ID}`,
        submitted_at: NOW,
      },
      202,
    );
  });

  await page.goto("/training");
  await page.getByRole("button", { name: "Create training job" }).first().click();
  await page.getByLabel("Registered dataset version").check();
  await page.getByLabel("Ready dataset version").selectOption(READY_VERSION_ID);
  await expect(
    page
      .getByLabel("Ready dataset version")
      .locator(`option[value="${PROCESSING_VERSION_ID}"]`),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Submit training job" }).dblclick();

  await expect(page).toHaveURL(new RegExp(`/training/${JOB_ID}$`));
  expect(creates).toBe(1);
  expect(submitted).toMatchObject({
    algorithm: "linear_regression",
    dataset_version_id: READY_VERSION_ID,
    task_type: "regression",
  });
  expect(submitted).not.toHaveProperty("training_features");
  expect(submitted).not.toHaveProperty("evaluation_features");
});

test("manual training keeps the backward-compatible inline matrix mode", async ({
  page,
}) => {
  await authenticated(page);
  await registeredDatasetRoutes(page);
  await page.route("**/ai/algorithms", (route) => json(route, [algorithm]));
  await page.route("**/ai/training-jobs?**", (route) =>
    json(route, { items: [], limit: 20, offset: 0, total: 0 }),
  );
  await page.route(`**/ai/training-jobs/${JOB_ID}`, (route) =>
    json(route, trainingJob()),
  );

  let creates = 0;
  let submitted: Record<string, unknown> | null = null;
  await page.route("**/ai/training-jobs", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    creates += 1;
    submitted = route.request().postDataJSON() as Record<string, unknown>;
    await json(
      route,
      {
        job_id: JOB_ID,
        status: "queued",
        status_url: `/ai/training-jobs/${JOB_ID}`,
        submitted_at: NOW,
      },
      202,
    );
  });

  await page.goto("/training");
  await page.getByRole("button", { name: "Create training job" }).first().click();
  await expect(page.getByLabel("Inline matrices")).toBeChecked();
  await expect(page.getByLabel("Training features (JSON matrix)")).toBeVisible();
  await page.getByRole("button", { name: "Submit training job" }).dblclick();

  await expect(page).toHaveURL(new RegExp(`/training/${JOB_ID}$`));
  expect(creates).toBe(1);
  expect(submitted).toMatchObject({
    algorithm: "linear_regression",
    task_type: "regression",
  });
  expect(submitted).toHaveProperty("training_features");
  expect(submitted).toHaveProperty("evaluation_features");
  expect(submitted).not.toHaveProperty("dataset_version_id");
});

test("AutoML submits a registered version without inline matrix metadata", async ({
  page,
}) => {
  await authenticated(page);
  await registeredDatasetRoutes(page);
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
  await page.route(`**/ai/automl/studies/${STUDY_ID}/leaderboard`, (route) =>
    json(route, []),
  );
  await page.route(`**/ai/automl/studies/${STUDY_ID}/trials**`, (route) =>
    json(route, { items: [], limit: 20, offset: 0, total: 0 }),
  );
  await page.route(`**/ai/automl/studies/${STUDY_ID}`, (route) =>
    json(route, autoMLStudy()),
  );

  let creates = 0;
  let submitted: Record<string, unknown> | null = null;
  await page.route("**/ai/automl/studies", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    creates += 1;
    submitted = route.request().postDataJSON() as Record<string, unknown>;
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
  });

  await page.goto("/automl/new");
  await page.getByText("Ridge Regression").click();
  await page.getByLabel("Registered dataset version").check();
  await page.getByLabel("Ready dataset version").selectOption(READY_VERSION_ID);
  await page.getByRole("button", { name: "Create and start study" }).dblclick();

  await expect(page).toHaveURL(new RegExp(`/automl/studies/${STUDY_ID}$`));
  expect(creates).toBe(1);
  expect(submitted).toMatchObject({
    data: { dataset_version_id: READY_VERSION_ID },
    task_type: "regression",
  });
  const data = (submitted as { data: Record<string, unknown> } | null)?.data;
  expect(data).not.toHaveProperty("training_features");
  expect(data).not.toHaveProperty("training_data_fingerprint");
});

test("registered dataset discovery pages through datasets and versions", async ({
  page,
}) => {
  await authenticated(page);
  await page.route("**/ai/algorithms", (route) => json(route, [algorithm]));
  await page.route("**/ai/training-jobs?**", (route) =>
    json(route, { items: [], limit: 20, offset: 0, total: 0 }),
  );
  const datasetIds = Array.from(
    { length: 20 },
    (_, index) => `40000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
  );
  await page.route("**/ai/datasets/*/versions?**", (route) => {
    const url = new URL(route.request().url());
    const datasetId = url.pathname.split("/").at(-2);
    const offset = Number(url.searchParams.get("offset") ?? "0");
    if (datasetId !== DATASET_ID) {
      return json(route, { items: [], limit: 100, offset, total: 0 });
    }
    if (offset === 0) {
      return json(route, {
        items: Array.from({ length: 100 }, (_, index) =>
          version(
            `50000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
            index + 1,
            "processing",
          ),
        ),
        limit: 100,
        offset,
        total: 101,
      });
    }
    return json(route, {
      items: [version(READY_VERSION_ID, 101, "ready")],
      limit: 100,
      offset,
      total: 101,
    });
  });
  await page.route("**/ai/datasets?**", (route) => {
    const url = new URL(route.request().url());
    const offset = Number(url.searchParams.get("offset") ?? "0");
    const items =
      offset === 0
        ? datasetIds.map((id, index) => ({
            archived_at: null,
            created_at: NOW,
            current_version_id: null,
            description: null,
            id,
            kind: "tabular",
            name: `Earlier dataset ${index + 1}`,
            owner_user_id: "engineer-id",
            state_version: 1,
            status: "active",
            updated_at: NOW,
          }))
        : [
            {
              archived_at: null,
              created_at: NOW,
              current_version_id: READY_VERSION_ID,
              description: null,
              id: DATASET_ID,
              kind: "tabular",
              name: "Page two dataset",
              owner_user_id: "engineer-id",
              state_version: 1,
              status: "active",
              updated_at: NOW,
            },
          ];
    return json(route, { items, limit: 20, offset, total: 21 });
  });

  await page.goto("/training");
  await page.getByRole("button", { name: "Create training job" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Create training job" });
  await dialog.getByLabel("Registered dataset version").check();
  await expect(dialog.getByText("Datasets 1–20 of 21")).toBeVisible();
  await dialog.getByRole("button", { name: "Next datasets" }).click();
  await expect(dialog.getByLabel("Ready dataset version")).toContainText(
    "Page two dataset · version 101",
  );
});

function trainingJob() {
  return {
    attempt_count: 0,
    cancelled_at: null,
    created_at: NOW,
    dataset_version_id: READY_VERSION_ID,
    error_code: null,
    finished_at: null,
    local_execution_run_id: null,
    max_attempts: 3,
    metrics: null,
    mlflow_experiment_id: null,
    mlflow_run_id: null,
    queued_at: NOW,
    registered_model_name: "linear_regression_model",
    registered_model_version: null,
    requested_by_user_id: "engineer-id",
    safe_error_message: null,
    started_at: null,
    status: "queued",
    trainer_key: { algorithm: "linear_regression", task_type: "regression" },
    job_id: JOB_ID,
  };
}

function autoMLStudy() {
  return {
    best_trial_id: null,
    cancel_requested_at: null,
    champion_training_job_id: null,
    created_at: NOW,
    cross_validation_folds: 2,
    data_specification: { dataset_version_id: READY_VERSION_ID },
    error_code: null,
    finished_at: null,
    max_concurrent_trials: 1,
    metric_direction: "minimize",
    per_trial_timeout_seconds: 60,
    plugin_ids: ["ridge_regression"],
    preprocessing: { imputer: "none", scaler: "auto" },
    primary_metric: "rmse",
    random_seed: 17,
    register_champion: false,
    registered_model_name: null,
    requested_by_user_id: "engineer-id",
    safe_error_message: null,
    sampler_type: "random",
    search_spaces: [],
    started_at: null,
    status: "queued",
    study_id: STUDY_ID,
    task_type: "regression",
    time_budget_seconds: 300,
    trial_budget: 2,
  };
}
