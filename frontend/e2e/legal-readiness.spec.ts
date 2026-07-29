import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function expectNoSeriousA11yViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.filter(
      ({ impact }) => impact === "critical" || impact === "serious",
    ),
  ).toEqual([]);
}

test.describe("legal review placeholders", () => {
  test("public legal pages are explicit unapproved placeholders", async ({ page }) => {
    await page.goto("/legal/privacy");

    await expect(
      page.getByRole("heading", { level: 1, name: "Privacy policy" }),
    ).toBeVisible();
    await expect(page.getByRole("note")).toContainText("not approved for production");
    await expect(page.getByRole("note")).toContainText("not legal advice");
    await expect(
      page.getByText("No acceptance is requested or recorded"),
    ).toBeVisible();
    await expect(
      page
        .getByRole("navigation", { name: "Legal and policy documents" })
        .getByRole("link"),
    ).toHaveCount(9);
    await expectNoSeriousA11yViolations(page);
  });

  test("registration links terms and privacy without fake consent", async ({
    page,
  }) => {
    await page.goto("/register");

    const registrationNotice = page
      .locator("p")
      .filter({ hasText: "registration does not record legal acceptance" });
    await expect(
      registrationNotice.getByRole("link", { name: "Terms", exact: true }),
    ).toBeVisible();
    await expect(
      registrationNotice.getByRole("link", { name: "Privacy policy", exact: true }),
    ).toBeVisible();
    await expect(registrationNotice).toBeVisible();
    await expect(page.getByRole("checkbox")).toHaveCount(0);
    await expectNoSeriousA11yViolations(page);
  });
});
