import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const enabled = process.env.E2E_REAL_BACKEND === "true";
const password = process.env.E2E_PASSWORD;
const accounts = {
  admin: process.env.E2E_ADMIN_EMAIL,
  engineer: process.env.E2E_ENGINEER_EMAIL,
  operator: process.env.E2E_OPERATOR_EMAIL,
} as const;

interface PageResult<T> {
  readonly items: readonly T[];
}

interface Factory {
  readonly id: string;
  readonly name: string;
}

interface Machine {
  readonly id: string;
  readonly name: string;
}

interface Sensor {
  readonly id: string;
  readonly name: string;
}

const browserErrors = new WeakMap<Page, string[]>();
const accessTokens = new WeakMap<Page, string>();

interface LoginResponse {
  readonly access_token: string;
}

async function login(page: Page, email: string | undefined): Promise<void> {
  if (!email || !password) throw new Error("Real-backend credentials are required.");
  await page.context().clearCookies();
  await page.goto("/login");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  const response = page.waitForResponse(
    (value) =>
      value.url().includes("/auth/login") && value.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Sign in" }).click();
  const loginResponse = await response;
  expect(loginResponse.status()).toBe(200);
  const tokens = (await loginResponse.json()) as LoginResponse;
  accessTokens.set(page, tokens.access_token);
  await expect(page.getByRole("button", { name: /Open account menu/ })).toBeVisible();
}

async function token(page: Page): Promise<string> {
  const accessToken = accessTokens.get(page);
  if (!accessToken) throw new Error("Browser access token is missing.");
  return accessToken;
}

async function api<T>(page: Page, path: string): Promise<T> {
  const response = await page.request.get(`/api${path}`, {
    headers: { Authorization: `Bearer ${await token(page)}` },
  });
  if (!response.ok()) {
    throw new Error(`GET ${path} returned ${response.status()}`);
  }
  return response.json() as Promise<T>;
}

async function hierarchy(page: Page): Promise<{
  factory: Factory;
  machine: Machine;
  sensor: Sensor;
}> {
  const factories = await api<PageResult<Factory>>(page, "/factories?limit=100");
  const factory = factories.items[0];
  if (!factory) throw new Error("Seeded factory is unavailable.");
  const machines = await api<PageResult<Machine>>(
    page,
    `/machines?factory_id=${factory.id}&limit=100`,
  );
  const machine = machines.items[0];
  if (!machine) throw new Error("Seeded machine is unavailable.");
  const sensors = await api<PageResult<Sensor>>(
    page,
    `/machines/${machine.id}/sensors?limit=100`,
  );
  const sensor = sensors.items[0];
  if (!sensor) throw new Error("Seeded sensor is unavailable.");
  return { factory, machine, sensor };
}

async function expectAccessible(page: Page): Promise<void> {
  const result = await new AxeBuilder({ page }).analyze();
  expect(
    result.violations.filter(
      ({ impact }) => impact === "critical" || impact === "serious",
    ),
  ).toEqual([]);
}

test.describe("Sprints 3-5 real-backend acceptance", () => {
  test.describe.configure({ mode: "serial" });
  test.skip(!enabled, "Set E2E_REAL_BACKEND=true for staging-like validation.");
  test.beforeEach(async ({ page }) => {
    const errors: string[] = [];
    browserErrors.set(page, errors);
    page.on("console", (entry) => {
      if (
        entry.type() === "error" &&
        !entry.text().startsWith("Failed to load resource: the server responded")
      )
        errors.push(entry.text());
    });
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("response", (response) => {
      const expectedMissingSession =
        response.url().includes("/auth/refresh") &&
        [401, 403].includes(response.status());
      if (response.status() >= 400 && !expectedMissingSession)
        errors.push(
          `${response.status()} ${response.request().method()} ${response.url()}`,
        );
    });
  });
  test.afterEach(async ({ page }) => {
    expect(browserErrors.get(page) ?? []).toEqual([]);
  });

  test("engineer completes valid onboarding and sees blocking invalid quality", async ({
    page,
  }) => {
    await login(page, accounts.engineer);
    const { machine, sensor } = await hierarchy(page);
    await page.goto("/sensor-data/onboarding");
    await expect(page.locator("#onboarding-heading")).toBeVisible();
    await page.getByLabel("CSV file").setInputFiles({
      buffer: Buffer.from(
        `timestamp,machine,sensor,value\n2026-07-24T10:00:00Z,${machine.name},${sensor.name},72.5\n2026-07-24T10:01:00Z,${machine.name},${sensor.name},73.0\n`,
      ),
      mimeType: "text/csv",
      name: "e2e-guided-valid.csv",
    });
    const upload = page.waitForResponse(
      (response) =>
        response.url().includes("/data-onboarding/imports") &&
        response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Upload for preview" }).click();
    expect((await upload).status()).toBe(201);
    await expect(page.getByText("e2e-guided-valid.csv")).toBeVisible();
    await page.getByRole("button", { name: "Confirm column mapping" }).click();
    await page.getByRole("button", { name: "Validate data" }).click();
    await page.getByRole("button", { name: "Confirm and import" }).click();
    await expect(page.getByText("completed", { exact: true })).toBeVisible();
    await expectAccessible(page);

    await page.getByLabel("CSV file").setInputFiles({
      buffer: Buffer.from(
        `timestamp,machine,sensor,value\n2026-07-24T10:00:00Z,${machine.name},${sensor.name},=2+2\n`,
      ),
      mimeType: "text/csv",
      name: "e2e-guided-invalid.csv",
    });
    await page.getByRole("button", { name: "Upload for preview" }).click();
    await page.getByRole("button", { name: "Confirm column mapping" }).click();
    await page.getByRole("button", { name: "Validate data" }).click();
    await expect(page.getByText(/Blocking · formula_like_values/)).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Confirm and import" }),
    ).toBeDisabled();
    await page.goto("/sensor-data/quality");
    await expect(page.locator("#quality-heading")).toBeVisible();
    await expectAccessible(page);
    await page.goto("/guided-ai");
    await expect(page.locator("#guided-ai-heading")).toBeVisible();
    await expectAccessible(page);
  });

  test("operator is denied expert onboarding and guided training", async ({ page }) => {
    await login(page, accounts.operator);
    await page.goto("/sensor-data/onboarding");
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("link", { name: "Data Onboarding" })).toHaveCount(0);
    await page.goto("/guided-ai");
    await expect(page).toHaveURL(/\/$/);
  });

  test("admin runs deterministic warning flow and opens map and TV mode", async ({
    page,
  }) => {
    await login(page, accounts.admin);
    const { factory, machine } = await hierarchy(page);
    await page.goto("/demo/control");
    await expect(page.locator("#demo-control-heading")).toBeVisible();
    await page
      .getByLabel("Guided demo tour")
      .getByRole("button", { name: "Skip" })
      .click();
    await page.getByLabel("Demo factory").selectOption(factory.id);
    await page.getByLabel("Demo machine").selectOption(machine.id);
    await page.getByLabel("Demo scenario").selectOption("warning_threshold");
    const started = page.waitForResponse(
      (response) =>
        response.url().includes("/demo/runs") && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Start scenario" }).click();
    const startedResponse = await started;
    expect(startedResponse.status()).toBe(201);
    const runId = String(((await startedResponse.json()) as { id: string }).id);
    try {
      const firstAdvance = page.waitForResponse(
        (response) =>
          response.url().endsWith(`/demo/runs/${runId}/advance`) &&
          response.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Advance" }).click();
      expect((await firstAdvance).status()).toBe(200);
      const secondAdvance = page.waitForResponse(
        (response) =>
          response.url().endsWith(`/demo/runs/${runId}/advance`) &&
          response.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Advance" }).click();
      const secondResponse = await secondAdvance;
      expect(secondResponse.status()).toBe(200);
      expect(
        (
          (await secondResponse.json()) as {
            state_snapshot: { risk_state: string };
          }
        ).state_snapshot.risk_state,
      ).toBe("warning");
      await expect(page.getByText(/Risk: warning/)).toBeVisible();
      await expectAccessible(page);

      await page.goto(`/factories/${factory.id}/map`);
      await expect(page.locator("#factory-map-heading")).toBeVisible();
      await expect(
        page.getByRole("link", { name: machine.name, exact: true }),
      ).toBeVisible();
      await expectAccessible(page);
      await page.goto(`/factories/${factory.id}/tv`);
      await expect(page.locator("#tv-heading")).toBeVisible();
      await expect(page.getByText("Authenticated read-only display")).toBeVisible();
      await expect(
        page.getByRole("button", { name: /Edit|Reset|Advance/ }),
      ).toHaveCount(0);
      await expectAccessible(page);
    } finally {
      const reset = await page.request.delete(`/api/demo/runs/${runId}/reset`, {
        headers: { Authorization: `Bearer ${await token(page)}` },
      });
      expect(reset.status()).toBe(200);
    }
  });

  test("admin drills into grounded metrics and downloads three report formats", async ({
    page,
  }) => {
    await login(page, accounts.admin);
    await page.goto("/executive");
    await expect(page.locator("#executive-heading")).toBeVisible();
    await expect(page.getByText(/No cost savings, ROI/)).toBeVisible();
    await expectAccessible(page);
    await page.goto("/reports");
    await expect(page.locator("#reports-heading")).toBeVisible();
    for (const format of ["PDF", "XLSX", "CSV"]) {
      const response = page.waitForResponse(
        (value) =>
          value.url().includes("/reporting/reports") &&
          value.request().method() === "POST",
      );
      await page.getByRole("button", { name: `Generate ${format}` }).click();
      expect((await response).status()).toBe(201);
    }
    await page.getByRole("link", { name: "Open" }).first().click();
    await expect(page.locator("#report-detail-heading")).toBeVisible();
    await expectAccessible(page);
  });
});
