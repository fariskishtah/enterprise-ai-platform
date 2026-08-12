import { expect, test, type Page, type Route } from "@playwright/test";

const API_PATTERN = /^http:\/\/(?:localhost|127\.0\.0\.1):8000(\/.*)$/;
const NOW = "2026-08-11T00:00:00Z";
const COMPANY_ID = "00000000-0000-4000-8000-000000000101";

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

async function mockEmptyOwnerWorkspace(page: Page): Promise<void> {
  await page.route(API_PATTERN, (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/auth/refresh") {
      return json(route, {
        access_token: "product-navigation-test-token",
        expires_in: 3600,
        token_type: "bearer",
      });
    }
    if (url.pathname === "/users/me") {
      return json(route, {
        company_id: COMPANY_ID,
        created_at: NOW,
        email: "owner@e2e.example.local",
        full_name: "Factory Owner",
        id: "product-navigation-owner",
        is_active: true,
        is_email_verified: true,
        role: "owner",
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
    if (url.pathname === "/companies") {
      return json(route, {
        items: [
          {
            created_at: NOW,
            description: "Private manufacturing workspace",
            id: COMPANY_ID,
            name: "Northstar Manufacturing",
            updated_at: NOW,
          },
        ],
        limit: 100,
        offset: 0,
        total: 1,
      });
    }
    return json(route, { items: [], limit: 20, offset: 0, total: 0 });
  });
}

test.describe("product information architecture", () => {
  test("guides an Owner from an empty workspace through grouped navigation", async ({
    page,
  }) => {
    await mockEmptyOwnerWorkspace(page);
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Factory overview" })).toBeVisible();
    await expect(page.getByText("Start here", { exact: true })).toBeVisible();
    await expect(page.getByText("1 · Factory", { exact: true })).toBeVisible();
    await expect(page.getByText("2 · Data", { exact: true })).toBeVisible();
    await expect(page.getByText("3 · Insight", { exact: true })).toBeVisible();

    const navigation = page.getByRole("navigation", { name: "Primary navigation" });
    for (const section of [
      "Overview",
      "Operations",
      "AI & Knowledge",
      "Advanced AI",
      "Monitoring",
      "Administration",
      "Commercial",
    ]) {
      await expect(navigation.getByRole("button", { name: section })).toBeVisible();
    }

    const advancedAi = navigation.getByRole("button", { name: "Advanced AI" });
    await expect(advancedAi).toHaveAttribute("aria-expanded", "false");
    await expect(navigation.getByRole("link", { name: "Datasets" })).toHaveCount(0);
    await advancedAi.click();
    await expect(advancedAi).toHaveAttribute("aria-expanded", "true");
    await expect(navigation.getByRole("link", { name: "Datasets" })).toBeVisible();

    await navigation.getByRole("link", { name: "Factories & Assets" }).click();
    await expect(page).toHaveURL(/\/factories$/);
    await expect(
      page.getByRole("heading", { name: "Factories", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Create factory" }).first(),
    ).toBeVisible();
  });

  test("keeps the grouped navigation usable on a narrow screen", async ({ page }) => {
    await page.setViewportSize({ height: 844, width: 390 });
    await mockEmptyOwnerWorkspace(page);
    await page.goto("/");

    await page.getByRole("button", { name: "Open navigation" }).click();
    const dialog = page.getByRole("dialog", { name: "Mobile navigation" });
    await expect(dialog.getByText("FactoryMind", { exact: true })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Operations" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );

    await dialog.getByRole("link", { name: "Factories & Assets" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page).toHaveURL(/\/factories$/);
    await expect(
      page.getByRole("heading", { name: "Factories", exact: true }),
    ).toBeVisible();
  });
});
