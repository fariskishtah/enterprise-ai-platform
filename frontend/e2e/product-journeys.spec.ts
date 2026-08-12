import { expect, test, type Page, type Route } from "@playwright/test";

type Role = "admin" | "analyst" | "engineer" | "owner" | "viewer";

const API_PATTERN = /^http:\/\/(?:localhost|127\.0\.0\.1):8000(\/.*)$/;
const NOW = "2026-08-11T00:00:00Z";
const COMPANY_ID = "00000000-0000-4000-8000-000000000201";
const FACTORY_ID = "00000000-0000-4000-8000-000000000202";
const MACHINE_ID = "00000000-0000-4000-8000-000000000203";

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function emptyPage(limit = 20): Record<string, unknown> {
  return { items: [], limit, offset: 0, total: 0 };
}

async function mockPersona(page: Page, role: Role): Promise<void> {
  await page.route(API_PATTERN, (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/auth/refresh") {
      return json(route, {
        access_token: "product-journey-test-token",
        expires_in: 3600,
        token_type: "bearer",
      });
    }
    if (url.pathname === "/users/me") {
      return json(route, {
        company_id: COMPANY_ID,
        created_at: NOW,
        email: `${role}@e2e.example.local`,
        full_name: `${role} journey user`,
        id: `product-journey-${role}`,
        is_active: true,
        is_email_verified: true,
        role,
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
    if (url.pathname === "/operations/summary") {
      return json(route, {
        action_counts: { open: 1 },
        active_shift_count: 1,
        alert_counts: { open: 1 },
        data_freshness_seconds: 180,
        overdue_actions: 0,
        risk_counts: { normal: 3, observe: 1 },
        unassigned_urgent_actions: 0,
      });
    }
    if (url.pathname.startsWith("/operations/")) {
      return json(route, emptyPage(6));
    }
    if (url.pathname === "/companies") {
      return json(route, {
        items: [
          {
            created_at: NOW,
            description: "Private product journey workspace",
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
    if (url.pathname === `/companies/${COMPANY_ID}`) {
      return json(route, {
        created_at: NOW,
        description: "Private product journey workspace",
        id: COMPANY_ID,
        name: "Northstar Manufacturing",
        updated_at: NOW,
      });
    }
    if (url.pathname === "/factories") {
      return json(route, {
        items: [
          {
            company_id: COMPANY_ID,
            created_at: NOW,
            description: "Primary manufacturing site",
            id: FACTORY_ID,
            location: "Cairo",
            name: "Northstar Plant",
            updated_at: NOW,
          },
        ],
        limit: Number(url.searchParams.get("limit") ?? 20),
        offset: 0,
        total: 1,
      });
    }
    if (url.pathname === `/factories/${FACTORY_ID}`) {
      return json(route, {
        company_id: COMPANY_ID,
        created_at: NOW,
        description: "Primary manufacturing site",
        id: FACTORY_ID,
        location: "Cairo",
        name: "Northstar Plant",
        updated_at: NOW,
      });
    }
    if (url.pathname === "/machines") {
      return json(route, {
        items: [
          {
            created_at: NOW,
            factory_id: FACTORY_ID,
            id: MACHINE_ID,
            manufacturer: "Acme",
            model: "Press 200",
            name: "Press 01",
            serial_number: "PRESS-01",
            updated_at: NOW,
          },
        ],
        limit: Number(url.searchParams.get("limit") ?? 20),
        offset: 0,
        total: 1,
      });
    }
    if (url.pathname === `/machines/${MACHINE_ID}`) {
      return json(route, {
        created_at: NOW,
        factory_id: FACTORY_ID,
        id: MACHINE_ID,
        manufacturer: "Acme",
        model: "Press 200",
        name: "Press 01",
        serial_number: "PRESS-01",
        updated_at: NOW,
      });
    }
    return json(route, emptyPage(Number(url.searchParams.get("limit") ?? 20)));
  });
}

test.describe("Phase 2 product journeys", () => {
  test("operations failures stay actionable without exposing diagnostics", async ({
    page,
  }) => {
    await mockPersona(page, "admin");
    await page.route("**/operations/summary", (route) =>
      json(
        route,
        {
          detail:
            "internal queue identifier and provider correlation must not reach users",
        },
        500,
      ),
    );
    await page.goto("/");

    const error = page.getByRole("alert");
    await expect(error).toContainText("Service unavailable");
    await expect(error).toContainText("try again shortly");
    await expect(error.getByRole("button", { name: "Try again" })).toBeVisible();
    await expect(page.getByText(/provider correlation/i)).toHaveCount(0);
    await expect(page.getByText("Technical detail")).toHaveCount(0);
  });

  test("Factory Owner follows the primary factory-to-data journey", async ({
    page,
  }) => {
    await mockPersona(page, "owner");
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Factory overview" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Manage your team" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Review plan & usage" })).toBeVisible();
    await page.getByRole("link", { name: "Northstar Plant" }).click();

    await expect(page.getByText("Current production structure")).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: "Factory → Machine or production asset → Sensor",
      }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Add machine" })).toBeVisible();
    await page.getByRole("link", { name: "Open machine" }).click();

    await expect(
      page.getByRole("button", { name: "Add sensor" }).first(),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Open Data Onboarding" }),
    ).toBeVisible();
  });

  test("Operations Manager receives an operations-first workflow", async ({ page }) => {
    await mockPersona(page, "admin");
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: "Operations manager overview" }),
    ).toBeVisible();
    await expect(page.getByText("Current machine risk states")).toBeVisible();
    await expect(
      page
        .getByLabel("Continue your workflow")
        .getByRole("link", { name: "Monitoring" }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Operational reports" })).toBeVisible();
    await expect(page.getByText("Operations Manager", { exact: true })).toBeVisible();
  });

  test("Engineer sees writable data and advanced AI workflows", async ({ page }) => {
    await mockPersona(page, "engineer");
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: "Data & AI workspace" }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Bring in machine data" }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Prepare trusted documents" }),
    ).toBeVisible();
    const navigation = page.getByRole("navigation", { name: "Primary navigation" });
    await expect(
      navigation.getByRole("button", { name: "Advanced AI" }),
    ).toHaveAttribute("aria-expanded", "true");

    await page.goto("/training");
    await expect(
      page.getByRole("button", { name: "Create training job" }).first(),
    ).toBeVisible();
  });

  test("Data Analyst receives coherent read-only engineering access", async ({
    page,
  }) => {
    const browserErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") browserErrors.push(message.text());
    });
    page.on("pageerror", (error) => browserErrors.push(error.message));
    await mockPersona(page, "analyst");
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: "Data & AI workspace" }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Review available models" }),
    ).toBeVisible();
    const navigation = page.getByRole("navigation", { name: "Primary navigation" });
    await expect(
      navigation.getByRole("button", { name: "Advanced AI" }),
    ).toHaveAttribute("aria-expanded", "true");
    await expect(navigation.getByRole("link", { name: "Data Onboarding" })).toHaveCount(
      0,
    );
    await expect(navigation.getByRole("link", { name: "Guided AI" })).toHaveCount(0);

    await page.goto("/datasets");
    await expect(
      page.getByRole("heading", { name: "Datasets & Documents" }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Add data or documents" })).toHaveCount(
      0,
    );
    await page.goto("/datasets/new");
    await expect(
      page.getByRole("heading", { name: "Access restricted" }),
    ).toBeVisible();
    await page.goto("/training");
    await expect(
      page.getByRole("heading", { name: "Training jobs", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Create training job" })).toHaveCount(
      0,
    );
    await page.goto("/automl");
    await expect(
      page.getByRole("heading", { name: "AutoML Studio", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Create study" })).toHaveCount(0);
    await page.goto("/audit-log");
    await expect(page.getByRole("heading", { name: "Audit Logs" })).toBeVisible();
    await page.goto("/chat");
    await expect(page.getByRole("heading", { name: "Read-only access" })).toBeVisible();
    expect(browserErrors).toEqual([]);
  });

  test("Viewer receives a read-only operational journey without false actions", async ({
    page,
  }) => {
    await mockPersona(page, "viewer");
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: "Read-only operations overview" }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Recent activity" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Operational reports" })).toHaveCount(
      0,
    );
    const navigation = page.getByRole("navigation", { name: "Primary navigation" });
    await expect(navigation.getByRole("button", { name: "Advanced AI" })).toHaveCount(
      0,
    );

    await page.goto("/factories");
    await expect(
      page.getByRole("heading", { name: "Factories", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Create factory" })).toHaveCount(0);
  });
});
