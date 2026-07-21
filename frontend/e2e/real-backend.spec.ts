import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const password = process.env.E2E_PASSWORD;
const accounts = {
  admin: process.env.E2E_ADMIN_EMAIL,
  engineer: process.env.E2E_ENGINEER_EMAIL,
  operator: process.env.E2E_OPERATOR_EMAIL,
} as const;
const enabled = process.env.E2E_REAL_BACKEND === "true";

async function login(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill(password ?? "");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/, { timeout: 20_000 });
}

function collectUnexpectedBrowserErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

test.describe("real staging backend", () => {
  test.describe.configure({ mode: "serial" });
  test.skip(!enabled, "Set E2E_REAL_BACKEND=true for the staging-like runtime.");

  for (const role of ["admin", "engineer", "operator"] as const) {
    test(`${role} authenticates and receives real role navigation`, async ({
      page,
    }) => {
      const email = accounts[role];
      test.skip(!email || !password, "Disposable role credentials are required.");
      const errors = collectUnexpectedBrowserErrors(page);
      await login(page, email ?? "");
      await page.goto("/settings");
      await expect(page.locator("#settings-heading")).toBeVisible();
      await expect(
        page.getByLabel("Profile").getByText(email ?? "", { exact: true }),
      ).toBeVisible();

      if (role === "operator") {
        await expect(page.getByRole("link", { name: "Training Jobs" })).toHaveCount(0);
        await expect(page.getByRole("link", { name: "Audit Logs" })).toHaveCount(0);
      } else {
        await expect(page.getByRole("link", { name: "Training Jobs" })).toBeVisible();
        await expect(page.getByRole("link", { name: "Audit Logs" })).toBeVisible();
      }
      expect(errors).toEqual([]);
    });
  }

  test("admin loads the real hierarchy and critical accessibility smoke", async ({
    page,
  }) => {
    test.skip(
      !accounts.admin || !password,
      "Disposable admin credentials are required.",
    );
    const errors = collectUnexpectedBrowserErrors(page);
    await login(page, accounts.admin ?? "");
    await page.goto("/factories");
    await expect(page.locator("#factories-heading")).toBeVisible();
    const axe = await new AxeBuilder({ page }).analyze();
    expect(
      axe.violations.filter(
        ({ impact }) => impact === "critical" || impact === "serious",
      ),
    ).toEqual([]);
    expect(errors).toEqual([]);
  });
});
