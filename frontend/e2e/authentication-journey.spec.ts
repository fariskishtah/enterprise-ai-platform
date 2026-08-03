import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

const user = {
  company_id: "company-1",
  created_at: "2026-08-01T10:00:00Z",
  email: "owner@example.com",
  full_name: "Factory Owner",
  id: "user-1",
  is_active: true,
  is_email_verified: true,
  role: "owner",
  updated_at: "2026-08-01T10:00:00Z",
};

const PRODUCTION_API_PATTERN = /^https?:\/\/[^/]+\/api\//;

async function isolateApi(page: Page): Promise<void> {
  await page.route(PRODUCTION_API_PATTERN, (route) => json(route, {}));
}

async function unauthenticated(page: Page): Promise<void> {
  await isolateApi(page);
  await page.route("**/auth/refresh", (route) =>
    json(route, { detail: "No session" }, 401),
  );
}

test.describe("authentication journey", () => {
  test("login handles success, safe failures, password visibility, and keyboard submit", async ({
    page,
  }) => {
    await unauthenticated(page);
    let loginAttempts = 0;
    await page.route("**/auth/login", (route) => {
      loginAttempts += 1;
      const payload = route.request().postDataJSON() as {
        email: string;
        password: string;
      };
      if (payload.password === "Correct horse battery staple") {
        return json(route, {
          access_token: "access-token",
          expires_in: 900,
          token_type: "bearer",
        });
      }
      return json(route, { detail: "internal credential lookup detail" }, 401);
    });
    await page.route("**/users/me", (route) => json(route, user));

    await page.goto("/login");
    await page.getByLabel("Work email").fill("owner@example.com");
    await page.getByLabel("Password", { exact: true }).fill("wrong-password");
    await page.getByRole("button", { name: "Show password" }).click();
    await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute(
      "type",
      "text",
    );
    await page.getByLabel("Password", { exact: true }).press("Enter");
    await expect(page.getByRole("alert")).toContainText("email or password");
    await expect(page.getByRole("alert")).not.toContainText("internal credential");

    await page
      .getByLabel("Password", { exact: true })
      .fill("Correct horse battery staple");
    await page.getByLabel("Password", { exact: true }).press("Enter");
    await expect(page).toHaveURL(/\/$/);
    expect(loginAttempts).toBe(2);
  });

  test("forgot password blocks duplicate clicks and keeps confirmation private", async ({
    page,
  }) => {
    await unauthenticated(page);
    let submissions = 0;
    let release: (() => void) | undefined;
    await page.route("**/auth/password-reset/request", async (route) => {
      submissions += 1;
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      return json(route, {
        local_reset_token: null,
        message: "Backend message must not define public wording.",
      });
    });
    await page.goto("/forgot-password");
    await page.getByLabel("Work email").fill("someone@example.com");
    const submit = page.getByRole("button", { name: "Send reset link" });
    await submit.click();
    await expect(
      page.getByRole("button", { name: "Sending secure link…" }),
    ).toBeDisabled();
    await page.locator("form").dispatchEvent("submit");
    expect(submissions).toBe(1);
    release?.();
    await expect(page.getByRole("heading", { name: "Check your inbox" })).toBeVisible();
    await expect(page.getByRole("status")).toContainText("If an account matches");
    await expect(page.getByRole("status")).not.toContainText("Backend message");
  });

  test("reset form handles weak, mismatched, invalid, expired, used, and successful tokens", async ({
    page,
  }) => {
    await unauthenticated(page);
    let requests = 0;
    await page.route("**/auth/password-reset/complete", (route) => {
      requests += 1;
      const token = (route.request().postDataJSON() as { token: string }).token;
      if (token.startsWith("expired")) return json(route, { detail: "expired" }, 410);
      if (token.startsWith("used")) return json(route, { detail: "used" }, 409);
      if (token.startsWith("invalid")) return json(route, { detail: "invalid" }, 422);
      return route.fulfill({ status: 204 });
    });

    await page.goto(`/reset-password?token=${"valid" + "a".repeat(43)}`);
    await page.getByLabel("New password", { exact: true }).fill("too-short");
    await page.getByLabel("Confirm new password", { exact: true }).fill("too-short");
    await page.getByRole("button", { name: "Save new password" }).click();
    await expect(page.getByRole("alert")).toContainText("12 and 128");
    expect(requests).toBe(0);

    await page
      .getByLabel("New password", { exact: true })
      .fill("a secure factory passphrase");
    await page
      .getByLabel("Confirm new password", { exact: true })
      .fill("a different factory passphrase");
    await page.getByRole("button", { name: "Save new password" }).click();
    await expect(page.getByRole("alert")).toContainText("does not match");
    expect(requests).toBe(0);

    for (const [prefix, heading] of [
      ["invalid", "This reset link is not valid"],
      ["expired", "This reset link has expired"],
      ["used", "This reset link was already used"],
    ] as const) {
      await page.goto(
        `/reset-password?token=${prefix + "b".repeat(48 - prefix.length)}`,
      );
      await page
        .getByLabel("New password", { exact: true })
        .fill("a secure factory passphrase");
      await page
        .getByLabel("Confirm new password", { exact: true })
        .fill("a secure factory passphrase");
      await page.getByRole("button", { name: "Save new password" }).click();
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
      await expect(
        page.getByRole("link", { name: "Request a new reset link" }),
      ).toBeVisible();
    }

    await page.goto(`/reset-password?token=${"success" + "c".repeat(41)}`);
    await page
      .getByLabel("New password", { exact: true })
      .fill("a secure factory passphrase");
    await page
      .getByLabel("Confirm new password", { exact: true })
      .fill("a secure factory passphrase");
    await page.getByRole("button", { name: "Save new password" }).click();
    await expect(
      page.getByRole("heading", { name: "You’re ready to sign in" }),
    ).toBeVisible();
  });

  test("registration prevents duplicates and maps an existing account to a recovery action", async ({
    page,
  }) => {
    await unauthenticated(page);
    let submissions = 0;
    await page.route("**/auth/register", (route) => {
      submissions += 1;
      return json(route, { detail: "Email is already registered." }, 409);
    });
    await page.goto("/register");
    await page.getByLabel("Full name").fill("Factory Owner");
    await page.getByLabel("Company name").fill("Precision Works");
    await page.getByLabel("Work email").fill("owner@example.com");
    await page
      .getByLabel("Password", { exact: true })
      .fill("a secure factory passphrase");
    await page
      .getByLabel("Confirm password", { exact: true })
      .fill("a secure factory passphrase");
    await page.getByRole("button", { name: "Create workspace" }).click();
    await expect(page.getByRole("alert")).toContainText("already uses these details");
    await expect(
      page.getByRole("alert").getByRole("link", { name: "Sign in instead" }),
    ).toBeVisible();
    expect(submissions).toBe(1);
  });

  test("resends verification once and exposes a clear cooldown", async ({ page }) => {
    await isolateApi(page);
    await page.route("**/auth/refresh", (route) =>
      json(route, {
        access_token: "access-token",
        expires_in: 900,
        token_type: "bearer",
      }),
    );
    await page.route("**/users/me", (route) =>
      json(route, { ...user, is_email_verified: false }),
    );
    await page.route("**/auth/email-verification/status", (route) =>
      json(route, {
        email: user.email,
        is_verified: false,
        resend_available_in_seconds: 0,
        verified_at: null,
      }),
    );
    let resends = 0;
    await page.route("**/auth/email-verification/resend", (route) => {
      resends += 1;
      return json(route, {
        local_verification_token: null,
        message: "queued",
        resend_available_in_seconds: 60,
      });
    });
    await page.goto("/verify-email");
    await page.getByRole("button", { name: "Resend verification email" }).click();
    await expect(
      page.getByText("A fresh verification link has been queued."),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /Resend available in/ }),
    ).toBeDisabled();
    expect(resends).toBe(1);
  });

  test("refresh failure produces a visible session-expired recovery state", async ({
    page,
  }) => {
    await isolateApi(page);
    let refreshes = 0;
    await page.route("**/auth/refresh", (route) => {
      refreshes += 1;
      return refreshes === 1
        ? json(route, {
            access_token: "access-token",
            expires_in: 900,
            token_type: "bearer",
          })
        : json(route, { detail: "expired" }, 401);
    });
    await page.route("**/users/me", (route) => json(route, user));
    await page.route("**/product/experience", (route) => json(route, {}));
    await page.route("**/users/me/sessions", (route) =>
      json(route, { detail: "expired" }, 401),
    );
    await page.goto("/settings");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("status")).toContainText("session expired");
  });

  test("change password validates confirmation, submits once, and signs out", async ({
    page,
  }) => {
    await isolateApi(page);
    await page.route("**/auth/refresh", (route) =>
      json(route, {
        access_token: "access-token",
        expires_in: 900,
        token_type: "bearer",
      }),
    );
    await page.route("**/users/me", (route) => json(route, user));
    await page.route("**/product/experience", (route) => json(route, {}));
    await page.route("**/users/me/sessions", (route) => json(route, { items: [] }));
    await page.route("**/auth/logout", (route) => route.fulfill({ status: 204 }));
    let changes = 0;
    await page.route("**/users/me/password", (route) => {
      changes += 1;
      expect(route.request().postDataJSON()).toEqual({
        current_password: "current factory passphrase",
        new_password: "new secure factory passphrase",
      });
      return route.fulfill({ status: 204 });
    });

    await page.goto("/settings#change-password");
    await page
      .getByLabel("Current password", { exact: true })
      .fill("current factory passphrase");
    await page
      .getByLabel("New password", { exact: true })
      .fill("new secure factory passphrase");
    await page
      .getByLabel("Confirm new password", { exact: true })
      .fill("different secure passphrase");
    await page.getByRole("button", { name: "Change password" }).click();
    await expect(page.getByRole("alert")).toContainText("confirmation does not match");
    expect(changes).toBe(0);

    await page
      .getByLabel("Confirm new password", { exact: true })
      .fill("new secure factory passphrase");
    await page.getByRole("button", { name: "Change password" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("status")).toContainText("signed out");
    expect(changes).toBe(1);
  });

  test("login is accessible and responsive on mobile", async ({ page }) => {
    await unauthenticated(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
    await page.keyboard.press("Tab");
    const themeButton = page.getByRole("button", { name: "Use dark mode" });
    await expect(themeButton).toBeFocused();
    expect(
      await themeButton.evaluate((element) => getComputedStyle(element).outlineStyle),
    ).not.toBe("none");
    await page.keyboard.press("Tab");
    const email = page.getByLabel("Work email");
    await expect(email).toBeFocused();
    await expect(email).toHaveAttribute("inputmode", "email");
    expect(await email.evaluate((element) => getComputedStyle(element).fontSize)).toBe(
      "16px",
    );
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
    await expect(page.locator("body")).toHaveCSS("overflow-x", "hidden");
  });
});
