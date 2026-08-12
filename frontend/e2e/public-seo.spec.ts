import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const PRODUCTION_ORIGIN = "https://factorymind.ddnsgeek.com";

test.describe("public FactoryMind landing and discoverability", () => {
  test("landing page explains the product and offers clear next actions", async ({
    page,
  }) => {
    await page.goto("/");

    await expect(page).toHaveTitle(
      "FactoryMind | Industrial AI for Manufacturing Operations",
    );
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: "Turn trusted manufacturing data into grounded operational decisions.",
      }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Create account" })).toHaveAttribute(
      "href",
      "/register",
    );
    await expect(page.getByRole("link", { name: "Request a demo" })).toHaveAttribute(
      "href",
      /^mailto:fkishtah@gmail\.com/,
    );
    await expect(page.getByRole("link", { name: "Sign in" }).first()).toHaveAttribute(
      "href",
      "/login",
    );
    await expect(
      page.getByText("Factory → Machine / Production Asset → Sensor"),
    ).toBeVisible();

    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(
      accessibility.violations.filter(
        ({ impact }) => impact === "critical" || impact === "serious",
      ),
    ).toEqual([]);
  });

  test("landing remains usable without horizontal overflow on mobile", async ({
    page,
  }) => {
    await page.setViewportSize({ height: 844, width: 390 });
    await page.goto("/");

    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "Create account" })).toBeVisible();
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth > document.documentElement.clientWidth,
      ),
    ).toBe(false);
  });

  test("document metadata uses the canonical production identity", async ({ page }) => {
    await page.goto("/");

    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      /industrial AI and operational intelligence platform/i,
    );
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
      "content",
      /index, follow/,
    );
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      "href",
      `${PRODUCTION_ORIGIN}/`,
    );
    await expect(page.locator('meta[property="og:title"]')).toHaveAttribute(
      "content",
      /FactoryMind/,
    );
    await expect(page.locator('meta[property="og:url"]')).toHaveAttribute(
      "content",
      `${PRODUCTION_ORIGIN}/`,
    );
    await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute(
      "content",
      "summary_large_image",
    );
    await expect(page.locator('link[rel="icon"]')).toHaveAttribute(
      "href",
      "/favicon.svg",
    );
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
  });

  test("robots and sitemap are real static crawler resources", async ({ request }) => {
    const robots = await request.get("/robots.txt");
    expect(robots.ok()).toBe(true);
    expect(robots.headers()["content-type"]).toContain("text/plain");
    expect(await robots.text()).toContain(`Sitemap: ${PRODUCTION_ORIGIN}/sitemap.xml`);

    const sitemap = await request.get("/sitemap.xml");
    expect(sitemap.ok()).toBe(true);
    expect(sitemap.headers()["content-type"]).toMatch(/xml/);
    expect(await sitemap.text()).toContain(`<loc>${PRODUCTION_ORIGIN}/</loc>`);

    const manifest = await request.get("/site.webmanifest");
    expect(manifest.ok()).toBe(true);
    expect((await manifest.json()).name).toBe("FactoryMind");
  });
});
