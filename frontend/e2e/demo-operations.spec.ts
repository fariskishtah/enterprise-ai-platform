import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const enabled = process.env.E2E_REAL_BACKEND === "true";
const password = process.env.E2E_PASSWORD;
const accounts = {
  admin: process.env.E2E_ADMIN_EMAIL,
  engineer: process.env.E2E_ENGINEER_EMAIL,
  operator: process.env.E2E_OPERATOR_EMAIL,
} as const;
const namespace = (
  process.env.E2E_RESOURCE_NAMESPACE ??
  process.env.GITHUB_RUN_ID ??
  "local-demo-operations"
)
  .replace(/[^A-Za-z0-9_.-]/g, "-")
  .slice(0, 40);
const runIdentity = Date.now().toString(36);

interface PageResponse<T> {
  readonly items: readonly T[];
  readonly total: number;
}

interface Factory {
  readonly id: string;
  readonly name: string;
}

interface Machine {
  readonly id: string;
  readonly name: string;
}

interface Assignee {
  readonly email: string;
  readonly id: string;
}

interface Action {
  readonly assigned_user_id: string | null;
  readonly factory_id: string;
  readonly id: string;
  readonly machine_id: string;
  readonly status: string;
  readonly title: string;
  readonly version: number;
}

interface Alert {
  readonly factory_id: string | null;
  readonly id: string;
  readonly lifecycle_version: number;
  readonly machine_id: string | null;
  readonly status: string;
}

interface Shift {
  readonly id: string;
  readonly status: string;
  readonly team_label: string | null;
}

let action: Action | null = null;
let alert: Alert | null = null;
let shift: Shift | null = null;
const browserErrors = new WeakMap<Page, string[]>();
const savedSessions = new Map<string, string>();

async function login(page: Page, email: string | undefined): Promise<void> {
  if (!email || !password) throw new Error("Real-backend credentials are required.");
  const savedSession = savedSessions.get(email);
  await page.goto("/login");
  await page.evaluate(() => sessionStorage.clear());
  if (savedSession) {
    await page.evaluate(
      (value) => sessionStorage.setItem("factorymind.auth.tokens", value),
      savedSession,
    );
    const identityResponse = page.waitForResponse(
      (item) => item.url().includes("/users/me") && item.request().method() === "GET",
    );
    await page.reload();
    expect((await identityResponse).status()).toBe(200);
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("button", { name: /Sign out/ })).toBeVisible();
    return;
  }
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill(password);
  const response = page.waitForResponse(
    (item) => item.url().includes("/auth/login") && item.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Sign in" }).click();
  expect((await response).status()).toBe(200);
  await expect(page).toHaveURL(/\/$/);
  savedSessions.set(
    email,
    await page.evaluate(() => sessionStorage.getItem("factorymind.auth.tokens") ?? ""),
  );
}

async function accessToken(page: Page): Promise<string> {
  return page.evaluate(() => {
    const raw = sessionStorage.getItem("factorymind.auth.tokens");
    if (!raw) throw new Error("Browser session token is unavailable.");
    return (JSON.parse(raw) as { accessToken: string }).accessToken;
  });
}

async function api<T>(
  page: Page,
  method: "GET" | "POST",
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await page.request.fetch(`/api${path}`, {
    data: body,
    headers: { Authorization: `Bearer ${await accessToken(page)}` },
    method,
  });
  if (!response.ok()) {
    throw new Error(
      `${method} ${path} returned ${response.status()}: ${await response.text()}`,
    );
  }
  return response.json() as Promise<T>;
}

async function clickAndWaitForMutation(
  page: Page,
  pathSuffix: string,
  click: () => Promise<void>,
  expectedStatus = 200,
): Promise<void> {
  const response = page.waitForResponse(
    (item) =>
      new URL(item.url()).pathname.endsWith(pathSuffix) &&
      item.request().method() === "POST",
  );
  await click();
  expect((await response).status()).toBe(expectedStatus);
}

async function expectAccessible(page: Page): Promise<void> {
  const result = await new AxeBuilder({ page }).analyze();
  expect(
    result.violations.filter(
      ({ impact }) => impact === "critical" || impact === "serious",
    ),
  ).toEqual([]);
}

test.describe("demo operations with real staging backend", () => {
  test.describe.configure({ mode: "serial" });
  test.skip(!enabled, "Set E2E_REAL_BACKEND=true for the staging-like runtime.");
  test.beforeEach(async ({ page }) => {
    const errors: string[] = [];
    browserErrors.set(page, errors);
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    page.on("pageerror", (error) => errors.push(error.message));
  });
  test.afterEach(async ({ page }) => {
    expect(browserErrors.get(page) ?? []).toEqual([]);
  });

  test("operator and engineer receive their fixed product modes", async ({ page }) => {
    await login(page, accounts.operator);
    await expect(page.locator("#simple-home-heading")).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Required Actions", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Training Jobs" })).toHaveCount(0);
    await expect(page.getByLabel("Product experience")).toHaveCount(0);
    await expectAccessible(page);

    await login(page, accounts.engineer);
    await expect(
      page.getByRole("link", { name: "Training Jobs", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Required Actions" })).toHaveCount(0);
    await expect(page.getByLabel("Product experience")).toHaveCount(0);
  });

  test("admin creates and assigns a deterministic operational action", async ({
    page,
  }) => {
    await login(page, accounts.admin);
    await page.getByLabel("Product experience").selectOption("simple");

    const factories = await api<PageResponse<Factory>>(
      page,
      "GET",
      "/factories?limit=100&offset=0",
    );
    const factory = factories.items[0];
    if (!factory) throw new Error("The deterministic factory seed is missing.");
    const machines = await api<PageResponse<Machine>>(
      page,
      "GET",
      `/machines?factory_id=${factory.id}&limit=100&offset=0`,
    );
    const machine = machines.items[0];
    if (!machine) throw new Error("The deterministic machine seed is missing.");
    const assignees = await api<readonly Assignee[]>(
      page,
      "GET",
      "/operations/assignees",
    );
    const operator = assignees.find((item) => item.email === accounts.operator);
    if (!operator) throw new Error("The deterministic operator is missing.");

    const titlePrefix = `E2E inspect spindle ${namespace}`;
    const existing = await api<PageResponse<Action>>(
      page,
      "GET",
      "/operations/actions?limit=100&offset=0",
    );
    action =
      existing.items.find(
        (item) =>
          item.title.startsWith(titlePrefix) &&
          !["completed", "cancelled"].includes(item.status),
      ) ??
      (await api<Action>(page, "POST", "/operations/actions", {
        factory_id: factory.id,
        machine_id: machine.id,
        priority: "critical",
        reason: "E2E warning condition requires a bounded operator inspection.",
        recommended_action: "Inspect spindle lubrication at the next safe stop.",
        title: `${titlePrefix} ${existing.items.length + 1}`,
      }));

    await page.goto(`/operations/actions/${action.id}`);
    await expect(page.locator("#action-heading")).toHaveText(action.title);
    if (action.status === "open") {
      await page.getByLabel("Assignee").selectOption(operator.id);
      await clickAndWaitForMutation(
        page,
        `/operations/actions/${action.id}/assign`,
        () => page.getByRole("button", { name: "Assign", exact: true }).click(),
      );
    }
    await expect(page.getByText("assigned", { exact: true })).toBeVisible();
  });

  test("operator acknowledges starts completes and annotates assigned work", async ({
    page,
  }) => {
    if (!action) throw new Error("The assigned action setup did not complete.");
    await login(page, accounts.operator);
    await page.goto(`/operations/actions/${action.id}`);
    await clickAndWaitForMutation(
      page,
      `/operations/actions/${action.id}/acknowledge`,
      () => page.getByRole("button", { name: "Acknowledge" }).click(),
    );
    await expect(page.getByRole("button", { name: "Start work" })).toBeVisible();
    await clickAndWaitForMutation(
      page,
      `/operations/actions/${action.id}/transition`,
      () => page.getByRole("button", { name: "Start work" }).click(),
    );
    await expect(page.getByRole("button", { name: "Complete" })).toBeVisible();
    await page
      .getByLabel("Add operator note")
      .fill("E2E operator inspection began at a safe machine stop.");
    await clickAndWaitForMutation(
      page,
      `/operations/actions/${action.id}/notes`,
      () => page.getByRole("button", { name: "Add note" }).click(),
      201,
    );
    await expect(
      page.getByText("E2E operator inspection began at a safe machine stop."),
    ).toBeVisible();
    await page
      .getByLabel("Completion, block, or reopen summary")
      .fill("E2E spindle inspection completed; no unsafe condition remains.");
    await clickAndWaitForMutation(
      page,
      `/operations/actions/${action.id}/transition`,
      () => page.getByRole("button", { name: "Complete" }).click(),
    );
    await expect(page.getByText("completed", { exact: true })).toBeVisible();
    await page
      .getByLabel("Human feedback summary")
      .fill("E2E maintenance inspection confirmed the work was completed.");
    await clickAndWaitForMutation(
      page,
      "/operations/maintenance-feedback",
      () => page.getByRole("button", { name: "Submit immutable feedback" }).click(),
      201,
    );
    await expect(
      page.getByText("E2E maintenance inspection confirmed the work was completed."),
    ).toBeVisible();
    await expectAccessible(page);
  });

  test("admin assigns and resolves the deterministic machine alert", async ({
    page,
  }) => {
    if (!action) throw new Error("The assigned action setup did not complete.");
    await login(page, accounts.admin);
    await page.getByLabel("Product experience").selectOption("simple");
    const alerts = await api<PageResponse<Alert>>(
      page,
      "GET",
      `/operations/alerts?machine_id=${action.machine_id}&limit=100&offset=0`,
    );
    alert = alerts.items[0] ?? null;
    if (!alert) throw new Error("The deterministic machine alert seed is missing.");

    const transition = async (
      kind: "acknowledge" | "assign" | "reopen" | "resolve" | "start",
      extra: Record<string, unknown> = {},
    ): Promise<void> => {
      alert = await api<Alert>(
        page,
        "POST",
        `/operations/alerts/${alert!.id}/lifecycle`,
        {
          expected_version: alert!.lifecycle_version,
          transition: kind,
          ...extra,
        },
      );
    };
    if (alert.status === "resolved") {
      await transition("reopen", { reopen_reason: "E2E follow-up verification." });
    }
    const assignees = await api<readonly Assignee[]>(
      page,
      "GET",
      "/operations/assignees",
    );
    const operator = assignees.find((item) => item.email === accounts.operator);
    if (!operator) throw new Error("The deterministic operator is missing.");
    await transition("assign", { assigned_user_id: operator.id });
    if (alert.status === "escalated") await transition("acknowledge");
    if (alert.status === "open") {
      await transition("acknowledge", {
        note: "E2E alert acknowledged for spindle inspection.",
      });
    }
    if (alert.status === "acknowledged") await transition("start");
    if (alert.status === "in_progress") {
      await transition("resolve", {
        resolution_classification: "maintenance_performed",
        resolution_summary: "E2E spindle inspection completed and verified.",
      });
    }
    expect(alert.status).toBe("resolved");
  });

  test("operator sees the unified machine timeline", async ({ page }) => {
    if (!action || !alert)
      throw new Error("The action and alert timeline setup did not complete.");
    await login(page, accounts.operator);
    await page.goto(
      `/factories/${action.factory_id}/machines/${action.machine_id}/timeline`,
    );
    await expect(
      page.locator(`a[href="/operations/actions/${action.id}"]`).first(),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Operational action assigned" }).first(),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Operator note added" }).first(),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Alert assign" }).first(),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Alert resolve" }).first(),
    ).toBeVisible();
    await expect(
      page.getByText(/E2E spindle inspection completed/).first(),
    ).toBeVisible();
    await expectAccessible(page);
  });

  test("operator completes and acknowledges a shift handover", async ({ page }) => {
    if (!action) throw new Error("The assigned action setup did not complete.");
    await login(page, accounts.operator);
    const active = await api<PageResponse<Shift>>(
      page,
      "GET",
      `/operations/shifts?factory_id=${action.factory_id}&status=active&limit=20&offset=0`,
    );
    shift = active.items[0] ?? null;
    if (!shift) {
      await page.goto("/operations/shifts");
      await page.getByLabel("Factory").selectOption(action.factory_id);
      await page.getByLabel("Operator or team label").fill(`E2E shift ${namespace}`);
      const createdResponse = page.waitForResponse(
        (response) =>
          response.url().includes("/operations/shifts") &&
          response.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Start shift" }).click();
      shift = (await (await createdResponse).json()) as Shift;
    }
    await page.goto(`/operations/shifts/${shift.id}`);
    if (shift.status === "active") {
      await page
        .getByLabel("Handover notes")
        .fill("E2E shift completed with the spindle inspection recorded.");
      await page
        .getByLabel("Unresolved items")
        .fill("No unresolved critical work remains from this E2E shift.");
      await clickAndWaitForMutation(page, `/operations/shifts/${shift.id}/end`, () =>
        page.getByRole("button", { name: "End shift and save handover" }).click(),
      );
      await expect(
        page.getByRole("button", { name: "Acknowledge next-shift handover" }),
      ).toBeVisible();
    }
    await clickAndWaitForMutation(
      page,
      `/operations/shifts/${shift.id}/acknowledge`,
      () =>
        page.getByRole("button", { name: "Acknowledge next-shift handover" }).click(),
    );
    await expect(page.getByText("acknowledged", { exact: true })).toBeVisible();
    await expectAccessible(page);
  });

  test("operator action list and alert detail pass accessibility smoke", async ({
    page,
  }) => {
    if (!alert) throw new Error("The alert accessibility setup did not complete.");
    await login(page, accounts.operator);
    await page.goto("/operations/actions");
    await expect(page.locator("#actions-heading")).toBeVisible();
    await expectAccessible(page);
    await page.goto(`/monitoring/alerts/${alert.id}`);
    await expect(page.locator("#alert-heading")).toBeVisible();
    await expectAccessible(page);
  });

  test("operator home remains usable at the supported responsive sizes", async ({
    page,
  }) => {
    await login(page, accounts.operator);
    const viewports = [
      { height: 900, width: 1440 },
      { height: 800, width: 1280 },
      { height: 768, width: 1024 },
      { height: 1024, width: 768 },
      { height: 844, width: 390 },
    ];
    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      await page.goto("/");
      await expect(page.locator("#simple-home-heading")).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
    }
  });

  test("cross-company operational access receives the established safe denial", async ({
    page,
  }) => {
    if (!action || !password)
      throw new Error("Cross-company setup prerequisites are missing.");
    const externalEmail =
      `external-${namespace}-${runIdentity}@example.com`.toLowerCase();
    const registration = await page.request.post("/api/auth/register", {
      data: { email: externalEmail, password },
    });
    expect([201, 409]).toContain(registration.status());
    await login(page, externalEmail);
    const response = await page.request.get(`/api/operations/actions/${action.id}`, {
      headers: { Authorization: `Bearer ${await accessToken(page)}` },
    });
    expect(response.status()).toBe(404);
    expect(await response.json()).toEqual({
      detail: "Operational action was not found.",
    });
  });
});
