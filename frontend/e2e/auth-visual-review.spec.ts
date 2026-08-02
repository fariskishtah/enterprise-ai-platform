import { expect, test, type Page, type Route } from "@playwright/test";

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

async function captureMatrix(page: Page, name: string): Promise<void> {
  const heading = page.locator("h1");
  await expect(heading).toBeVisible();

  await page.setViewportSize({ width: 1440, height: 1000 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    fullPage: true,
    path: `../artifacts/auth-screenshots/${name}-desktop-light.png`,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    fullPage: true,
    path: `../artifacts/auth-screenshots/${name}-mobile-light.png`,
  });

  await page.getByRole("button", { name: "Use dark mode" }).click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    fullPage: true,
    path: `../artifacts/auth-screenshots/${name}-desktop-dark.png`,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    fullPage: true,
    path: `../artifacts/auth-screenshots/${name}-mobile-dark.png`,
  });
  await page.getByRole("button", { name: "Use light mode" }).click();
}

test("captures the complete authentication visual review matrix", async ({ page }) => {
  let loginSucceeds = false;
  await page.route("**/auth/refresh", (route) =>
    json(route, { detail: "No active session" }, 401),
  );
  await page.route("**/users/me", (route) =>
    json(route, {
      company_id: "visual-company",
      created_at: "2026-08-01T10:00:00Z",
      email: "owner@precision.example",
      full_name: "Factory Owner",
      id: "visual-user",
      is_active: true,
      is_email_verified: false,
      role: "owner",
      updated_at: "2026-08-01T10:00:00Z",
    }),
  );
  await page.route("**/product/experience", (route) => json(route, {}));
  await page.route("**/auth/login", (route) =>
    loginSucceeds
      ? json(route, {
          access_token: "visual-access",
          expires_in: 900,
          token_type: "bearer",
        })
      : json(route, { detail: "Invalid credentials" }, 401),
  );
  await page.route("**/auth/logout", (route) => route.fulfill({ status: 204 }));
  await page.route("**/auth/password-reset/request", (route) =>
    json(route, {
      local_reset_token: null,
      message: "If the account exists, reset instructions are available.",
    }),
  );
  await page.route("**/auth/password-reset/complete", (route) => {
    const token = (route.request().postDataJSON() as { token: string }).token;
    if (token.startsWith("expired")) return json(route, { detail: "Expired" }, 410);
    return route.fulfill({ status: 204 });
  });
  await page.route("**/auth/email-verification/verify", (route) =>
    json(route, { message: "Your email has been verified.", status: "verified" }),
  );
  await page.route("**/auth/email-verification/status", (route) =>
    json(route, {
      email: "owner@precision.example",
      is_verified: false,
      resend_available_in_seconds: 0,
      verified_at: null,
    }),
  );
  await page.route("**/team/invitations/accept", (route) =>
    json(route, { status: "accepted", user: {} }),
  );

  await page.goto("/login");
  await captureMatrix(page, "01-login");

  await page.getByLabel("Work email").fill("owner@precision.example");
  await page.getByLabel("Password", { exact: true }).fill("incorrect password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await captureMatrix(page, "02-login-error");

  await page.goto("/forgot-password");
  await captureMatrix(page, "03-forgot-password");
  await page.getByLabel("Work email").fill("owner@precision.example");
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByRole("heading", { name: "Check your inbox" })).toBeVisible();
  await captureMatrix(page, "04-forgot-password-submitted");

  await page.goto(`/reset-password?token=${"valid" + "a".repeat(43)}`);
  await captureMatrix(page, "05-reset-password");

  await page.goto("/reset-password");
  await captureMatrix(page, "06-reset-invalid");

  await page.goto(`/reset-password?token=${"expired" + "b".repeat(41)}`);
  await page
    .getByLabel("New password", { exact: true })
    .fill("a secure factory passphrase");
  await page
    .getByLabel("Confirm new password", { exact: true })
    .fill("a secure factory passphrase");
  await page.getByRole("button", { name: "Save new password" }).click();
  await expect(
    page.getByRole("heading", { name: "This reset link has expired" }),
  ).toBeVisible();
  await captureMatrix(page, "07-reset-expired");

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
  await captureMatrix(page, "08-reset-success");

  await page.goto("/register");
  await captureMatrix(page, "09-register");

  loginSucceeds = true;
  await page.goto("/login");
  await page.getByLabel("Work email").fill("owner@precision.example");
  await page
    .getByLabel("Password", { exact: true })
    .fill("a secure factory passphrase");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/verify-email$/);
  await captureMatrix(page, "10-verification-required");
  await page.getByRole("button", { name: "Sign out and use another account" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.goto(`/verify-email?token=${"verified" + "d".repeat(40)}`);
  await expect(
    page.getByRole("heading", { name: "Your email is verified" }),
  ).toBeVisible();
  await captureMatrix(page, "11-verification-success");

  await page.goto(`/accept-invitation?token=${"invite" + "e".repeat(42)}`);
  await captureMatrix(page, "12-invitation");

  await page.goto("/accept-invitation");
  await captureMatrix(page, "13-invitation-invalid");

  await page.goto("/login?reason=session-expired");
  await expect(page.getByRole("status")).toContainText("session expired");
  await captureMatrix(page, "14-session-expired");
});
