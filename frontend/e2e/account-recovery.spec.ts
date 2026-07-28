import { expect, test, type Route } from "@playwright/test";

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

test.describe("account recovery", () => {
  test("accepts a new-user team invitation", async ({ page }) => {
    await page.route("**/team/invitations/accept", (route) =>
      json(route, {
        status: "accepted",
        user: {
          company_id: "invited-company",
          created_at: "2026-07-28T12:00:00Z",
          email: "invitee@example.com",
          full_name: "Invited User",
          id: "invited-user",
          is_active: true,
          is_email_verified: true,
          role: "analyst",
          updated_at: "2026-07-28T12:00:00Z",
        },
      }),
    );
    await page.goto(`/accept-invitation?token=${`invite${"a".repeat(43)}`}`);
    await page.getByLabel("Full name").fill("Invited User");
    await page.getByLabel("Password").fill("InvitationPassword1!");
    await page.getByRole("button", { name: "Accept invitation" }).click();
    await expect(
      page.getByRole("heading", { name: "Invitation accepted" }),
    ).toBeVisible();
    await expect(page.getByRole("status")).toContainText("account is ready");
  });

  test("shows successful and expired email verification states", async ({ page }) => {
    await page.route("**/auth/email-verification/verify", (route) => {
      const token = (route.request().postDataJSON() as { token: string }).token;
      return token.startsWith("valid")
        ? json(route, {
            message: "Your email has been verified.",
            status: "verified",
          })
        : json(route, { detail: "Verification token has expired." }, 410);
    });
    await page.goto(`/verify-email?token=${`valid${"a".repeat(43)}`}`);
    await expect(page.getByRole("heading", { name: "Email verified" })).toBeVisible();
    await expect(page.getByRole("status")).toContainText("has been verified");

    await page.goto(`/verify-email?token=${`expired${"b".repeat(41)}`}`);
    await expect(
      page.getByRole("heading", { name: "Verification link expired" }),
    ).toBeVisible();
  });

  test("requests reset instructions without disclosing account existence", async ({
    page,
  }) => {
    let submissions = 0;
    await page.route("**/auth/password-reset/request", async (route) => {
      submissions += 1;
      expect(route.request().postDataJSON()).toEqual({
        email: "owner@example.com",
      });
      return json(route, {
        local_reset_token: null,
        message: "If the account exists, password reset instructions are available.",
      });
    });
    await page.goto("/forgot-password");
    await page.getByLabel("Work email").fill("owner@example.com");
    await page.getByRole("button", { name: "Send reset instructions" }).click();
    await expect(page.getByRole("status")).toContainText("If the account exists");
    expect(submissions).toBe(1);
  });

  test("validates confirmation and completes a single reset request", async ({
    page,
  }) => {
    let submissions = 0;
    await page.route("**/auth/password-reset/complete", async (route) => {
      submissions += 1;
      expect(route.request().postDataJSON()).toEqual({
        new_password: "ChangedPassword1!",
        token: "a".repeat(48),
      });
      return route.fulfill({ status: 204 });
    });
    await page.goto(`/reset-password?token=${"a".repeat(48)}`);
    await page.getByLabel("New password", { exact: true }).fill("ChangedPassword1!");
    await page.getByLabel("Confirm new password").fill("MismatchPassword1!");
    await page.getByRole("button", { name: "Update password" }).click();
    await expect(page.getByRole("alert")).toContainText("Passwords do not match");
    expect(submissions).toBe(0);
    await page.getByLabel("Confirm new password").fill("ChangedPassword1!");
    await page.getByRole("button", { name: "Update password" }).click();
    await expect(page.getByRole("status")).toContainText("Password updated");
    expect(submissions).toBe(1);
  });
});
