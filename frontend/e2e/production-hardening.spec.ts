import { expect, test, type Page, type Route } from "@playwright/test";

const API_PATTERN = /^http:\/\/localhost:8000(\/.*)$/;
const NOW = "2026-01-01T00:00:00Z";
const COMPANY_ID = "00000000-0000-4000-8000-000000000099";

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

async function authenticate(page: Page): Promise<void> {
  await page.addInitScript(
    ({ expiresAt }) => {
      sessionStorage.setItem(
        "factorymind.auth.tokens",
        JSON.stringify({
          accessToken: "production-hardening-access-token",
          accessTokenExpiresAt: expiresAt,
          refreshToken: "production-hardening-refresh-token",
        }),
      );
    },
    { expiresAt: Date.now() + 3_600_000 },
  );
}

async function mockWorkspace(
  page: Page,
  supportStatus: "delivered" | "delivery_failed" = "delivered",
): Promise<{ logoutCount: () => number; submittedBodies: () => unknown[] }> {
  let logouts = 0;
  const submissions: unknown[] = [];
  await page.route(API_PATTERN, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/users/me") {
      return json(route, {
        company_id: COMPANY_ID,
        created_at: NOW,
        email: "engineer@e2e.example.local",
        full_name: "Production Engineer",
        id: "e2e-engineer",
        is_active: true,
        role: "engineer",
        updated_at: NOW,
      });
    }
    if (url.pathname === "/product/features") {
      return json(route, {
        demo_tools_enabled: false,
        operations_workflow_enabled: true,
        simplified_experience_enabled: true,
      });
    }
    if (url.pathname === `/companies/${COMPANY_ID}`) {
      return json(route, {
        created_at: NOW,
        description: "Production hardening test company",
        id: COMPANY_ID,
        name: "FK Manufacturing",
        updated_at: NOW,
      });
    }
    if (url.pathname === "/factories") {
      return json(route, { items: [], limit: 100, offset: 0, total: 0 });
    }
    if (url.pathname === "/support/requests" && request.method() === "POST") {
      submissions.push(request.postDataJSON());
      return json(
        route,
        {
          category: "technical_problem",
          created_at: NOW,
          current_page: "/support",
          delivered_at: supportStatus === "delivered" ? NOW : null,
          delivery_attempts: 1,
          delivery_message:
            supportStatus === "delivered"
              ? "Your support request was delivered."
              : "Your request was saved, but email delivery failed. An administrator can retry it.",
          factory_id: null,
          id: "00000000-0000-4000-8000-000000000111",
          machine_id: null,
          status: supportStatus,
          subject: "Production support request",
          updated_at: NOW,
        },
        201,
      );
    }
    if (url.pathname === "/auth/logout") {
      logouts += 1;
      return route.fulfill({ status: 204 });
    }
    return json(route, { items: [], limit: 20, offset: 0, total: 0 });
  });
  return {
    logoutCount: () => logouts,
    submittedBodies: () => submissions,
  };
}

test.describe("production account and support experience", () => {
  test("account disclosure is keyboard accessible and logout remains explicit", async ({
    page,
  }) => {
    await authenticate(page);
    const observations = await mockWorkspace(page);
    await page.goto("/settings");

    const accountButton = page.getByRole("button", {
      name: "Open account menu for engineer@e2e.example.local",
    });
    await expect(accountButton).toBeVisible();
    await accountButton.click();
    await expect(page.getByRole("menu", { name: "Account options" })).toBeVisible();
    expect(observations.logoutCount()).toBe(0);

    await page.getByRole("heading", { level: 2, name: "Settings" }).click();
    await expect(page.getByRole("menu", { name: "Account options" })).toHaveCount(0);

    await accountButton.click();
    await page.keyboard.press("ArrowDown");
    await expect(page.getByRole("menuitem", { name: "My Profile" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(accountButton).toBeFocused();
    await expect(page.getByRole("menu", { name: "Account options" })).toHaveCount(0);

    await accountButton.click();
    await page.getByRole("menuitem", { name: "My Profile" }).click();
    await expect(
      page.getByRole("heading", { level: 2, name: "My Profile" }),
    ).toBeVisible();
    await expect(page.getByRole("main").getByText("Production Engineer")).toBeVisible();
    expect(observations.logoutCount()).toBe(0);

    await accountButton.click();
    await page.getByRole("menuitem", { name: "Log Out" }).click();
    await expect(page).toHaveURL(/\/login$/);
    expect(observations.logoutCount()).toBe(1);
  });

  test("support submission reports real delivered and saved-failure states", async ({
    page,
  }) => {
    await authenticate(page);
    const delivered = await mockWorkspace(page, "delivered");
    await page.goto("/support");

    await page.getByLabel("Subject").fill("Production support request");
    await page
      .getByLabel("Message")
      .fill("A bounded test request for the production support workflow.");
    await page.getByRole("button", { name: "Submit support request" }).click();
    await expect(page.getByRole("status")).toContainText(
      "Your support request was delivered.",
    );
    expect(delivered.submittedBodies()).toHaveLength(1);
    expect(delivered.submittedBodies()[0]).toMatchObject({
      current_page: "/support",
      subject: "Production support request",
    });
  });

  test("support delivery failure is not presented as successful delivery", async ({
    page,
  }) => {
    await authenticate(page);
    await mockWorkspace(page, "delivery_failed");
    await page.goto("/support");

    await page.getByLabel("Subject").fill("Production support request");
    await page
      .getByLabel("Message")
      .fill("A bounded test request for the production support workflow.");
    await page.getByRole("button", { name: "Submit support request" }).click();
    await expect(page.getByRole("status")).toContainText(
      "saved, but email delivery failed",
    );
    await expect(page.getByText(/was delivered/i)).toHaveCount(0);
  });

  test("semantic sidebar motion preserves layout and honors reduced motion", async ({
    page,
  }) => {
    await authenticate(page);
    await mockWorkspace(page);
    await page.goto("/settings");

    const navigation = page.getByRole("navigation", {
      name: "Primary navigation",
    });
    const factoryLink = navigation.getByRole("link", { name: "Factory Overview" });
    await expect(factoryLink.locator('[data-motion="lift"]')).toHaveCount(1);
    await expect(
      navigation
        .getByRole("link", { name: "Home" })
        .locator('[data-motion="chart-rise"]'),
    ).toHaveCount(1);
    await expect(
      navigation
        .getByRole("link", { name: "Settings" })
        .locator('[data-motion="rotate"]'),
    ).toHaveCount(1);
    const before = await factoryLink.boundingBox();
    await factoryLink.hover();
    const after = await factoryLink.boundingBox();
    expect(after).toEqual(before);

    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.reload();
    const reducedFactoryLink = page
      .getByRole("navigation", { name: "Primary navigation" })
      .getByRole("link", { name: "Factory Overview" });
    await reducedFactoryLink.hover();
    const reducedMotionStyle = await reducedFactoryLink
      .locator('[data-motion="lift"]')
      .evaluate((element) => {
        const style = getComputedStyle(element);
        return {
          animationName: style.animationName,
          transform: style.transform,
          transitionDuration: style.transitionDuration,
        };
      });
    expect(reducedMotionStyle).toEqual({
      animationName: "none",
      transform: "none",
      transitionDuration: "0s",
    });
  });

  test("account menu remains usable without horizontal overflow on mobile", async ({
    page,
  }) => {
    await page.setViewportSize({ height: 844, width: 390 });
    await authenticate(page);
    await mockWorkspace(page);
    await page.goto("/settings");

    await page
      .getByRole("button", {
        name: "Open account menu for engineer@e2e.example.local",
      })
      .click();
    await expect(page.getByRole("menuitem", { name: "Contact Support" })).toBeVisible();
    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(hasHorizontalOverflow).toBe(false);
  });
});
