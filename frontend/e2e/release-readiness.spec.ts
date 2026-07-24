import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

type Role = "admin" | "engineer" | "operator";

const API_PATTERN = /^http:\/\/localhost:8000(\/.*)$/;
const NOW = "2026-01-01T00:00:00Z";

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

async function mockAuthenticatedUser(page: Page, role: Role): Promise<void> {
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
      created_at: NOW,
      email: `${role}@e2e.example.local`,
      id: `e2e-${role}`,
      is_active: true,
      role,
      updated_at: NOW,
    }),
  );
  await page.route("**/auth/logout", (route) => route.fulfill({ status: 204 }));
}

function observeBrowserFailures(page: Page): string[] {
  const failures: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") failures.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => failures.push(`pageerror: ${error.message}`));
  return failures;
}

async function expectNoSeriousA11yViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.filter(
      ({ impact }) => impact === "critical" || impact === "serious",
    ),
  ).toEqual([]);
}

test.describe("authentication", () => {
  test("anonymous users are redirected and invalid login feedback is safe", async ({
    page,
  }) => {
    const failures = observeBrowserFailures(page);
    await page.route("**/auth/login", (route) =>
      json(route, { detail: "Invalid email or password." }, 401),
    );

    await page.goto("/settings");
    await expect(page).toHaveURL(/\/login$/);
    await page.getByLabel("Email address").fill("invalid@example.local");
    await page.getByLabel("Password").fill("incorrect");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page.getByRole("alert")).toContainText("Invalid email or password");
    await expect(page).not.toHaveURL(/token|password/i);
    // Chromium reports an expected HTTP 401 from the intentionally invalid login as
    // a generic resource error. All other console and page errors remain failures.
    expect(failures.filter((message) => !message.includes("status of 401"))).toEqual(
      [],
    );
  });

  test("login, reload persistence, and logout preserve the session contract", async ({
    page,
  }) => {
    const failures = observeBrowserFailures(page);
    await page.route(API_PATTERN, (route) =>
      json(route, { items: [], limit: 20, offset: 0, total: 0 }),
    );
    await page.route("**/auth/login", (route) =>
      json(route, {
        access_token: "browser-test-access-token",
        expires_in: 3600,
        refresh_token: "browser-test-refresh-token",
        token_type: "bearer",
      }),
    );
    await page.route("**/users/me", (route) =>
      json(route, {
        created_at: NOW,
        email: "admin@e2e.example.local",
        id: "e2e-admin",
        is_active: true,
        role: "admin",
        updated_at: NOW,
      }),
    );
    await page.route("**/auth/logout", (route) => route.fulfill({ status: 204 }));

    await page.goto("/settings");
    await expect(page).toHaveURL(/\/login$/);
    await page.getByLabel("Email address").fill("admin@e2e.example.local");
    await page.getByLabel("Password").fill("local-test-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/settings$/);
    await page.reload();
    await expect(page.locator("#settings-heading")).toBeVisible();
    await page.getByRole("button", { name: /Sign out/ }).click();
    await expect(page).toHaveURL(/\/login$/);
    expect(failures).toEqual([]);
  });

  test("concurrent expired requests use one refresh and all resume", async ({
    page,
  }) => {
    let refreshCount = 0;
    await page.route("**/auth/refresh", async (route) => {
      refreshCount += 1;
      await new Promise((resolve) => setTimeout(resolve, 100));
      await json(route, {
        access_token: "refreshed-access-token",
        expires_in: 3600,
        refresh_token: "rotated-refresh-token",
        token_type: "bearer",
      });
    });
    await page.route("**/users/me", (route) => json(route, { id: "e2e-user" }));
    await page.goto("/login");
    await page.evaluate(() => {
      sessionStorage.setItem(
        "factorymind.auth.tokens",
        JSON.stringify({
          accessToken: "expired-access-token",
          accessTokenExpiresAt: 0,
          refreshToken: "initial-refresh-token",
        }),
      );
    });

    const results = await page.evaluate(async () => {
      const { apiRequest } = await import("/src/api/client.ts");
      return Promise.all([
        apiRequest<{ id: string }>("/users/me"),
        apiRequest<{ id: string }>("/users/me"),
        apiRequest<{ id: string }>("/users/me"),
      ]);
    });

    expect(refreshCount).toBe(1);
    expect(results).toEqual([
      { id: "e2e-user" },
      { id: "e2e-user" },
      { id: "e2e-user" },
    ]);
  });

  test("logout during refresh cannot restore a cleared session", async ({ page }) => {
    let releaseRefresh: (() => void) | undefined;
    let markRefreshStarted: (() => void) | undefined;
    const refreshStarted = new Promise<void>((resolve) => {
      markRefreshStarted = resolve;
    });
    await page.route("**/auth/refresh", async (route) => {
      markRefreshStarted?.();
      await new Promise<void>((release) => {
        releaseRefresh = release;
      });
      await json(route, {
        access_token: "late-access-token",
        expires_in: 3600,
        refresh_token: "late-refresh-token",
        token_type: "bearer",
      });
    });
    await page.goto("/login");
    await page.evaluate(() => {
      sessionStorage.setItem(
        "factorymind.auth.tokens",
        JSON.stringify({
          accessToken: "expired-access-token",
          accessTokenExpiresAt: 0,
          refreshToken: "initial-refresh-token",
        }),
      );
    });

    const pending = page.evaluate(async () => {
      const { apiRequest } = await import("/src/api/client.ts");
      try {
        await apiRequest("/users/me");
        return "resolved";
      } catch {
        return "rejected";
      }
    });
    await refreshStarted;
    await page.evaluate(() => sessionStorage.removeItem("factorymind.auth.tokens"));
    releaseRefresh?.();

    expect(await pending).toBe("rejected");
    expect(
      await page.evaluate(() => sessionStorage.getItem("factorymind.auth.tokens")),
    ).toBeNull();
  });
});

test.describe("role-aware navigation", () => {
  for (const role of ["admin", "engineer", "operator"] as const) {
    test(`${role} receives only its permitted navigation`, async ({ page }) => {
      const failures = observeBrowserFailures(page);
      await mockAuthenticatedUser(page, role);
      let restrictedAuditRequests = 0;
      await page.route(API_PATTERN, (route) => {
        if (route.request().url().endsWith("/users/me")) return route.fallback();
        if (route.request().url().endsWith("/auth/logout")) return route.fallback();
        if (route.request().url().includes("/ai/retraining/audits")) {
          restrictedAuditRequests += 1;
        }
        return json(route, { items: [], limit: 20, offset: 0, total: 0 });
      });
      const identityReady = page.waitForResponse(
        (response) => response.url().endsWith("/users/me") && response.status() === 200,
      );
      await page.goto("/settings");
      await identityReady;

      const navigation = page.getByRole("navigation", {
        name: "Primary navigation",
      });
      await expect(navigation.getByRole("link", { name: "Settings" })).toBeVisible();
      if (role === "operator") {
        await expect(navigation.getByRole("link", { name: "Dashboard" })).toBeVisible();
        await expect(navigation.getByRole("link", { name: "Models" })).toBeVisible();
        await expect(
          navigation.getByRole("link", { name: "Training Jobs" }),
        ).toHaveCount(0);
        await expect(navigation.getByRole("link", { name: "Audit Logs" })).toHaveCount(
          0,
        );
        const directRouteIdentityReady = page.waitForResponse(
          (response) =>
            response.url().endsWith("/users/me") && response.status() === 200,
        );
        await page.goto("/audit-log");
        await directRouteIdentityReady;
        await expect(page).toHaveURL(/\/audit-log$/);
        await expect(
          page.getByRole("heading", { name: "Administrator access required" }),
        ).toBeVisible();
        expect(restrictedAuditRequests).toBe(0);
      } else {
        await expect(
          navigation.getByRole("link", { name: "Training Jobs" }),
        ).toBeVisible();
        await expect(
          navigation.getByRole("link", { name: "Audit Logs" }),
        ).toBeVisible();
      }
      expect(failures).toEqual([]);
    });
  }
});

test.describe("themes, responsiveness, and accessibility", () => {
  test("light, dark, and system preferences persist", async ({ page }) => {
    await mockAuthenticatedUser(page, "admin");
    await page.goto("/settings");
    await page.getByLabel("Dark", { exact: true }).check();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.reload();
    await expect(page.getByLabel("Dark", { exact: true })).toBeChecked();

    await page.getByLabel("Light", { exact: true }).check();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.emulateMedia({ colorScheme: "dark" });
    await page.getByLabel("Use system setting").check();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.reload();
    await expect(page.getByLabel("Use system setting")).toBeChecked();
  });

  for (const viewport of [
    { height: 900, width: 1440 },
    { height: 800, width: 1280 },
    { height: 768, width: 1024 },
    { height: 1024, width: 768 },
    { height: 844, width: 390 },
  ]) {
    test(`settings has no page overflow at ${viewport.width}x${viewport.height}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await mockAuthenticatedUser(page, "admin");
      await page.goto("/settings");
      await expect(page.locator("#settings-heading")).toBeVisible();
      const dimensions = await page.evaluate(() => ({
        client: document.documentElement.clientWidth,
        scroll: document.documentElement.scrollWidth,
      }));
      expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.client);
    });
  }

  test("login and authenticated settings have no serious axe violations", async ({
    page,
  }) => {
    await page.goto("/login");
    await expectNoSeriousA11yViolations(page);
    await mockAuthenticatedUser(page, "admin");
    await page.goto("/settings");
    await expectNoSeriousA11yViolations(page);
  });
});
