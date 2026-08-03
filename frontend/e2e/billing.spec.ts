import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const API_PATTERN =
  /^(?:http:\/\/(?:localhost|127\.0\.0\.1):8000\/|https?:\/\/[^/]+\/api\/).*$/;
const NOW = "2026-07-29T10:00:00Z";
const PERIOD_END = "2026-08-29T10:00:00Z";
const PAYMENT_ID = "11111111-1111-4111-8111-111111111111";

const plans = [
  {
    code: "starter",
    currency: "EGP",
    description: "Core monitoring for a focused manufacturing team.",
    entitlements: {
      advanced_reports: false,
      audit_log: false,
      document_storage_gb: 2,
      documents: 100,
      factories: 1,
      machines: 25,
      monthly_rag_queries: 500,
      model_training: false,
      scheduled_reports: 0,
      team_members: 5,
      training_concurrency: 1,
    },
    monthly_price_minor: 100000,
    name: "Starter",
  },
  {
    code: "professional",
    currency: "EGP",
    description: "Higher limits and reporting for growing operations.",
    entitlements: {
      advanced_reports: true,
      audit_log: false,
      document_storage_gb: 25,
      documents: 2500,
      factories: 5,
      machines: 250,
      monthly_rag_queries: 5000,
      model_training: true,
      scheduled_reports: 10,
      team_members: 25,
      training_concurrency: 2,
    },
    monthly_price_minor: 500000,
    name: "Professional",
  },
  {
    code: "enterprise",
    currency: "EGP",
    description: "Maximum scale and governance for complex estates.",
    entitlements: {
      advanced_reports: true,
      audit_log: true,
      document_storage_gb: 250,
      documents: 25000,
      factories: 25,
      machines: 2000,
      monthly_rag_queries: 50000,
      model_training: true,
      scheduled_reports: 100,
      team_members: 100,
      training_concurrency: 10,
    },
    monthly_price_minor: 1000000,
    name: "Enterprise",
  },
] as const;

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json",
    status,
  });
}

function subscription(overrides: Record<string, unknown> = {}) {
  return {
    allowed_actions: ["upgrade", "downgrade", "cancel"],
    cancel_at_period_end: false,
    current_period_end: PERIOD_END,
    current_period_start: NOW,
    ended_at: null,
    grace_period_ends_at: null,
    pending_plan_code: null,
    plan_code: "professional",
    status: "active",
    subscription_id: "22222222-2222-4222-8222-222222222222",
    suspended_at: null,
    version: 3,
    ...overrides,
  };
}

function payment(status = "succeeded", overrides: Record<string, unknown> = {}) {
  const providerDecision =
    status === "succeeded"
      ? "succeeded_eligible"
      : status === "under_review"
        ? "under_review"
        : status === "expired"
          ? "expired"
          : status === "refunded" || status === "reversed"
            ? status
            : status === "failed"
              ? "failed"
              : "pending";
  const checkoutIntentStatus =
    status === "succeeded"
      ? "completed"
      : status === "failed"
        ? "failed"
        : status === "cancelled"
          ? "cancelled"
          : status === "expired"
            ? "expired"
            : "open";
  return {
    amount_minor: 500000,
    created_at: NOW,
    checkout_expires_at: PERIOD_END,
    checkout_intent_status: checkoutIntentStatus,
    commercial_model: "prepaid_manual_renewal",
    currency: "EGP",
    failure_code: status === "failed" ? "declined" : null,
    payment_id: PAYMENT_ID,
    plan_code: "professional",
    provider: "paymob",
    provider_checkout_id: "checkout-42",
    provider_occurred_at: NOW,
    provider_payment_id: "paymob-42",
    provider_decision: providerDecision,
    purpose: "renewal",
    status: ["under_review", "expired"].includes(status) ? "pending" : status,
    updated_at: NOW,
    ...overrides,
  };
}

const entitlements = {
  access_mode: "full_access",
  items: [
    {
      enabled: null,
      key: "team_members",
      limit: 25,
      over_limit: false,
      period_end: null,
      period_start: null,
      remaining: 17,
      source: "plan",
      used: 8,
    },
    {
      enabled: null,
      key: "monthly_rag_queries",
      limit: 5000,
      over_limit: false,
      period_end: PERIOD_END,
      period_start: NOW,
      remaining: 3750,
      source: "plan",
      used: 1250,
    },
    {
      enabled: true,
      key: "advanced_reports",
      limit: null,
      over_limit: false,
      period_end: null,
      period_start: null,
      remaining: null,
      source: "plan",
      used: null,
    },
  ],
  plan_code: "professional",
  recommended_plan: null,
  subscription_status: "active",
};

interface BillingMockOptions {
  readonly checkoutDelayMs?: number;
  readonly paymentStatus?: string;
  readonly role?: "owner" | "admin" | "engineer";
  readonly subscriptionOverrides?: Record<string, unknown>;
}

async function mockBilling(page: Page, options: BillingMockOptions = {}) {
  let currentSubscription = subscription(options.subscriptionOverrides);
  const requests: {
    cancellationCount: number;
    checkoutCount: number;
    directions: string[];
    unhandled: string[];
  } = {
    cancellationCount: 0,
    checkoutCount: 0,
    directions: [],
    unhandled: [],
  };
  await page.route(API_PATTERN, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/")) url.pathname = url.pathname.slice(4);
    if (url.pathname === "/auth/refresh") {
      return json(route, {
        access_token: "billing-e2e-access",
        expires_in: 3600,
        token_type: "bearer",
      });
    }
    if (url.pathname === "/users/me") {
      return json(route, {
        company_id: "33333333-3333-4333-8333-333333333333",
        created_at: NOW,
        email: "owner@example.local",
        full_name: "Mona Owner",
        id: "44444444-4444-4444-8444-444444444444",
        is_active: true,
        is_email_verified: true,
        role: options.role ?? "owner",
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
    if (url.pathname === "/billing/plans")
      return json(route, {
        commercial_model: "prepaid_manual_renewal",
        items: plans,
      });
    if (url.pathname === "/billing/subscription" && request.method() === "GET") {
      return json(route, { item: currentSubscription });
    }
    if (url.pathname === "/billing/entitlements") return json(route, entitlements);
    if (url.pathname === "/billing/history/payments") {
      return json(route, {
        items: [payment()],
        page: 1,
        page_size: 20,
        total: 1,
      });
    }
    if (url.pathname === "/billing/history/invoices") {
      return json(route, {
        items: [
          {
            amount_minor: 500000,
            currency: "EGP",
            invoice_id: "55555555-5555-4555-8555-555555555555",
            issued_at: NOW,
            payment_id: PAYMENT_ID,
            provider: "paymob",
            provider_invoice_id: "INV-2026-0042",
            receipt_url: "https://example.test/receipt/42",
            status: "paid",
          },
        ],
        page: 1,
        page_size: 20,
        total: 1,
      });
    }
    if (url.pathname === "/billing/admin/events") {
      return json(route, {
        items: [
          {
            action: "subscription.activated",
            actor_user_id: null,
            created_at: NOW,
            event_id: "66666666-6666-4666-8666-666666666666",
            result: "succeeded",
            safe_metadata: { plan_code: "professional" },
          },
        ],
        page: 1,
        page_size: 20,
        total: 1,
      });
    }
    if (url.pathname === "/billing/admin/provider-events") {
      return json(route, {
        items: [
          {
            attempts: 1,
            event_id: "77777777-7777-4777-8777-777777777777",
            event_type: "payment_succeeded",
            last_error: null,
            processed_at: NOW,
            provider: "paymob",
            provider_event_id: "evt-paymob-42",
            received_at: NOW,
            status: "processed",
          },
        ],
        page: 1,
        page_size: 20,
        total: 1,
      });
    }
    if (url.pathname === `/billing/payments/${PAYMENT_ID}`) {
      return json(route, payment(options.paymentStatus ?? "succeeded"));
    }
    if (url.pathname === "/billing/returns/resolve" && request.method() === "POST") {
      const body = request.postDataJSON() as { state?: string };
      return body.state === "phase2-return-state"
        ? json(route, payment(options.paymentStatus ?? "succeeded"))
        : json(route, { detail: "This payment return link is unavailable." }, 404);
    }
    if (url.pathname === "/billing/subscription/cancel") {
      requests.cancellationCount += 1;
      currentSubscription = subscription({
        allowed_actions: ["upgrade", "downgrade", "cancel", "reactivate"],
        cancel_at_period_end: true,
        version: 4,
      });
      return json(route, currentSubscription);
    }
    if (url.pathname === "/billing/subscription/reactivate") {
      currentSubscription = subscription({ version: 5 });
      return json(route, currentSubscription);
    }
    if (
      url.pathname === `/billing/payments/${PAYMENT_ID}/cancel` &&
      request.method() === "POST"
    ) {
      return json(route, payment("cancelled"));
    }
    if (
      ["/billing/subscription/upgrade", "/billing/subscription/downgrade"].includes(
        url.pathname,
      )
    ) {
      requests.checkoutCount += 1;
      requests.directions.push(url.pathname.split("/").at(-1) ?? "");
      if (options.checkoutDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.checkoutDelayMs));
      }
      const requestedPlan = request.postDataJSON() as { plan_code: string };
      return json(
        route,
        {
          amount_minor:
            plans.find((item) => item.code === requestedPlan.plan_code)
              ?.monthly_price_minor ?? 0,
          checkout_expires_at: PERIOD_END,
          checkout_url:
            "/settings/billing/return?state=phase2-return-state&success=true&amount=1&plan=enterprise",
          commercial_model: "prepaid_manual_renewal",
          currency: "EGP",
          failure_url: "http://127.0.0.1:5173/settings/billing/return",
          payment_id: PAYMENT_ID,
          plan_code: requestedPlan.plan_code,
          provider: "paymob",
          provider_checkout_id: "checkout-42",
          purpose: "plan_change",
          reused: false,
          status: "pending",
          subscription_id: currentSubscription.subscription_id,
        },
        201,
      );
    }
    requests.unhandled.push(`${request.method()} ${url.pathname}`);
    return json(route, { items: [], limit: 20, offset: 0, total: 0 });
  });
  return requests;
}

async function fillCheckout(page: Page): Promise<void> {
  await page.getByLabel("Phone number").fill("+201001234567");
  await page.getByLabel("City").fill("Cairo");
  await page.getByLabel("Street address").fill("10 Industrial Road");
}

test("public pricing renders backend plans for an unauthenticated visitor", async ({
  page,
}) => {
  await page.route("**/auth/refresh", (route) =>
    json(route, { detail: "No session" }, 401),
  );
  await page.route("**/billing/plans", (route) =>
    json(route, {
      commercial_model: "prepaid_manual_renewal",
      items: plans,
    }),
  );
  await page.goto("/pricing");
  await expect(
    page.getByRole("heading", { name: "Choose the operating scale your team needs" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Starter" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Create workspace" })).toHaveCount(3);
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/production-pricing-desktop-light.png",
  });
  expect(
    (await new AxeBuilder({ page }).analyze()).violations.filter(
      ({ impact }) => impact === "critical" || impact === "serious",
    ),
  ).toEqual([]);

  await page.evaluate(() => localStorage.setItem("fk-theme-preference", "dark"));
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(
    page.getByRole("heading", { name: "Choose the operating scale your team needs" }),
  ).toBeVisible();
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/production-pricing-desktop-dark.png",
  });
  expect(
    (await new AxeBuilder({ page }).analyze()).violations.filter(
      ({ impact }) => impact === "critical" || impact === "serious",
    ),
  ).toEqual([]);

  await page.setViewportSize({ height: 844, width: 390 });
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/production-pricing-mobile-dark.png",
  });
  await page.evaluate(() => localStorage.setItem("fk-theme-preference", "light"));
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Choose the operating scale your team needs" }),
  ).toBeVisible();
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/production-pricing-mobile-light.png",
  });
  expect(await page.evaluate(() => document.body.scrollWidth)).toBeLessThanOrEqual(390);
});

test("owner sees current plan, usage limits, payments, and invoices", async ({
  page,
}) => {
  const browserErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  const requests = await mockBilling(page);
  await page.goto("/settings/billing");
  await expect(
    page.getByRole("heading", { name: "Billing & subscription" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "professional", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("8 of 25")).toBeVisible();
  await expect(page.getByText("1,250 of 5,000")).toBeVisible();
  await expect(page.getByText("INV-2026-0042")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Provider event inspection" }),
  ).toBeVisible();
  await expect(page.getByText("evt-paymob-42")).toBeVisible();
  expect(
    (await new AxeBuilder({ page }).analyze()).violations.filter(
      ({ impact }) => impact === "critical" || impact === "serious",
    ),
  ).toEqual([]);
  await expect(
    page
      .getByRole("navigation", { name: "Primary navigation" })
      .getByRole("link", { name: "Billing" }),
  ).toBeVisible();
  expect(requests.unhandled).toEqual([]);
  expect(browserErrors).toEqual([]);
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/phase-h-billing-overview.png",
  });
  await page
    .locator("#current-plan-heading")
    .locator("xpath=ancestor::section[1]")
    .screenshot({ path: "../artifacts/screenshots/phase-h-current-subscription.png" });
  await page
    .locator("#usage-heading")
    .locator("xpath=ancestor::section[1]")
    .screenshot({ path: "../artifacts/screenshots/phase-h-usage-dashboard.png" });
  await page
    .locator("#payment-history-heading")
    .locator("xpath=ancestor::section[1]")
    .screenshot({ path: "../artifacts/screenshots/phase-h-payment-history.png" });
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/phase-h-admin-billing.png",
  });
});

test("billing overview remains readable across the production theme matrix", async ({
  page,
}) => {
  await mockBilling(page);
  await page.goto("/settings/billing");
  await expect(
    page.getByRole("heading", { name: "Billing & subscription" }),
  ).toBeVisible();

  for (const theme of ["light", "dark"] as const) {
    await page.evaluate(
      (preference) => localStorage.setItem("fk-theme-preference", preference),
      theme,
    );
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expect(
      page.getByRole("heading", { name: "Billing & subscription" }),
    ).toBeVisible();
    await page.setViewportSize({ height: 1000, width: 1440 });
    await page.screenshot({
      fullPage: true,
      path: `../artifacts/screenshots/production-billing-desktop-${theme}.png`,
    });
    expect(
      (await new AxeBuilder({ page }).analyze()).violations.filter(
        ({ impact }) => impact === "critical" || impact === "serious",
      ),
    ).toEqual([]);
    await page.setViewportSize({ height: 844, width: 390 });
    await page.screenshot({
      fullPage: true,
      path: `../artifacts/screenshots/production-billing-mobile-${theme}.png`,
    });
    expect(await page.evaluate(() => document.body.scrollWidth)).toBeLessThanOrEqual(
      390,
    );
  }
});

test("hosted upgrade redirect is followed but success query data is not trusted", async ({
  page,
}) => {
  const requests = await mockBilling(page);
  await page.goto("/settings/billing/checkout/enterprise");
  await fillCheckout(page);
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/phase-h-upgrade-checkout.png",
  });
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/phase-h-checkout.png",
  });
  await page.getByRole("button", { name: /Continue to Paymob/ }).click();
  await expect(page).toHaveURL(/state=phase2-return-state.*success=true/);
  await expect(page.getByRole("heading", { name: "Payment verified" })).toBeVisible();
  await expect(page.getByText(/professional ·/i)).toBeVisible();
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/phase-h-payment-success.png",
  });
  expect(requests.directions).toEqual(["upgrade"]);
});

test("pending payment stays in processing and offers an explicit refresh", async ({
  page,
}) => {
  await mockBilling(page, { paymentStatus: "pending" });
  await page.goto(
    "/settings/billing/return?state=phase2-return-state&success=true&amount=1&plan=starter",
  );
  await expect(page.getByRole("heading", { name: "Confirming payment" })).toBeVisible();
  await expect(page.getByText(/waiting for an eligible provider event/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Check again" })).toBeVisible();
});

test("failed payment offers a retry without claiming paid access", async ({ page }) => {
  await mockBilling(page, { paymentStatus: "failed" });
  await page.goto("/settings/billing/return?state=phase2-return-state&success=true");
  await expect(
    page.getByRole("heading", { name: "Payment was declined" }),
  ).toBeVisible();
  await expect(
    page.getByText("No paid access was granted.", { exact: false }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Start new checkout" })).toHaveAttribute(
    "href",
    "/settings/billing/checkout/professional",
  );
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/phase-h-payment-failure.png",
  });
});

test("cancelled payment remains inactive and is clearly disclosed", async ({
  page,
}) => {
  await mockBilling(page, { paymentStatus: "cancelled" });
  await page.goto("/settings/billing/return?state=phase2-return-state&success=true");
  await expect(page.getByRole("heading", { name: "Checkout cancelled" })).toBeVisible();
  await expect(page.getByText(/no paid access was granted/i)).toBeVisible();
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/phase-h-payment-cancellation.png",
  });
});

test("missing and tampered return states show safe recovery", async ({ page }) => {
  await mockBilling(page);
  await page.goto("/settings/billing/return?success=true&amount=500000");
  await expect(
    page.getByRole("heading", { name: "Unable to confirm payment" }),
  ).toBeVisible();
  await expect(page.getByText(/missing its secure state/i)).toBeVisible();
  await page.goto("/settings/billing/return?state=tampered-return-state-value-000000");
  await expect(
    page.getByRole("heading", { name: "Unable to confirm payment" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "View billing" })).toBeVisible();
});

test("expired and under-review returns provide recovery actions", async ({ page }) => {
  await mockBilling(page, { paymentStatus: "expired" });
  await page.goto("/settings/billing/return?state=phase2-return-state");
  await expect(page.getByRole("heading", { name: "Checkout expired" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Start new checkout" })).toBeVisible();

  await page.unrouteAll({ behavior: "wait" });
  await mockBilling(page, { paymentStatus: "under_review" });
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Payment under review" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Contact support" })).toBeVisible();
  await page.evaluate(() => localStorage.setItem("fk-theme-preference", "dark"));
  await page.setViewportSize({ height: 844, width: 390 });
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(
    page.getByRole("heading", { name: "Payment under review" }),
  ).toBeVisible();
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/phase2-payment-under-review-mobile-dark.png",
  });
  expect(await page.evaluate(() => document.body.scrollWidth)).toBeLessThanOrEqual(390);
  expect(
    (await new AxeBuilder({ page }).analyze()).violations.filter(
      ({ impact }) => impact === "critical" || impact === "serious",
    ),
  ).toEqual([]);
});

test("rapid checkout submissions create only one hosted checkout", async ({ page }) => {
  const requests = await mockBilling(page, { checkoutDelayMs: 400 });
  await page.goto("/settings/billing/checkout/enterprise");
  await fillCheckout(page);
  const submit = page.getByRole("button", { name: /Continue to Paymob/ });
  await submit.evaluate((element) => {
    (element as HTMLButtonElement).click();
    (element as HTMLButtonElement).click();
  });
  await expect(page.getByText("Opening Paymob…")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Payment verified" })).toBeVisible();
  expect(requests.checkoutCount).toBe(1);
});

test("subscription cancellation requires confirmation and preserves period access", async ({
  page,
}) => {
  const requests = await mockBilling(page);
  await page.goto("/settings/billing");
  await page.getByRole("button", { name: "Schedule cancellation" }).click();
  await expect(page.getByRole("alertdialog")).toContainText("No resources are deleted");
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/phase-h-cancellation-confirmation.png",
  });
  await page.getByRole("button", { name: "Confirm cancellation" }).click();
  await expect(page.getByText("Cancellation scheduled")).toBeVisible();
  expect(requests.cancellationCount).toBe(1);
});

test("scheduled cancellation can be reactivated", async ({ page }) => {
  await mockBilling(page, {
    subscriptionOverrides: {
      allowed_actions: ["upgrade", "downgrade", "cancel", "reactivate"],
      cancel_at_period_end: true,
    },
  });
  await page.goto("/settings/billing");
  await expect(page.getByText("Cancellation scheduled")).toBeVisible();
  await page.getByRole("button", { name: "Reactivate subscription" }).click();
  await expect(page.getByText("Cancellation scheduled")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Schedule cancellation" }),
  ).toBeVisible();
});

test("checkout selects the downgrade lifecycle endpoint", async ({ page }) => {
  const requests = await mockBilling(page);
  await page.goto("/settings/billing/checkout/starter");
  await fillCheckout(page);
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/phase-h-downgrade-checkout.png",
  });
  await page.getByRole("button", { name: /Continue to Paymob/ }).click();
  await expect(page.getByRole("heading", { name: "Payment verified" })).toBeVisible();
  expect(requests.directions).toEqual(["downgrade"]);
});

test("refund and reversal terminal states are disclosed", async ({ page }) => {
  await mockBilling(page, { paymentStatus: "refunded" });
  await page.goto("/settings/billing/return?state=phase2-return-state");
  await expect(page.getByRole("heading", { name: "Payment refunded" })).toBeVisible();
  await page.unrouteAll({ behavior: "wait" });
  await mockBilling(page, { paymentStatus: "reversed" });
  await page.reload();
  await expect(page.getByRole("heading", { name: "Payment reversed" })).toBeVisible();
});

test("suspended and expired subscriptions show state-aware recovery guidance", async ({
  page,
}) => {
  await mockBilling(page, {
    subscriptionOverrides: {
      allowed_actions: ["checkout_to_reactivate"],
      status: "suspended",
      suspended_at: NOW,
    },
  });
  await page.goto("/settings/billing");
  await expect(page.getByText("Workspace is read-only")).toBeVisible();
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/phase-h-suspended-state.png",
  });

  await page.unrouteAll({ behavior: "wait" });
  await mockBilling(page, {
    subscriptionOverrides: {
      allowed_actions: ["checkout_to_reactivate"],
      ended_at: NOW,
      status: "expired",
    },
  });
  await page.reload();
  await expect(page.getByText("Subscription inactive")).toBeVisible();
  await expect(
    page.getByText(/choose a plan and complete verified checkout/i),
  ).toBeVisible();
});

test("non-billing roles are denied and do not receive billing navigation", async ({
  page,
}) => {
  await mockBilling(page, { role: "engineer" });
  await page.goto("/settings/billing");
  await expect(page.getByRole("heading", { name: "Access restricted" })).toBeVisible();
  await expect(page.getByText(/does not permit this action/i)).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Primary navigation" })
      .getByRole("link", { name: "Billing" }),
  ).toHaveCount(0);
});

test("billing workspace remains usable on a narrow mobile viewport", async ({
  page,
}) => {
  await page.setViewportSize({ height: 844, width: 390 });
  await mockBilling(page, {
    subscriptionOverrides: {
      grace_period_ends_at: "2026-08-03T10:00:00Z",
      status: "past_due",
    },
  });
  await page.goto("/settings/billing");
  await expect(
    page.getByRole("heading", { name: "Billing & subscription" }),
  ).toBeVisible();
  await expect(page.getByText("Payment past due")).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    body: document.body.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(dimensions.body).toBeLessThanOrEqual(dimensions.viewport);
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/phase-h-billing-mobile.png",
  });
  await page.screenshot({
    fullPage: true,
    path: "../artifacts/screenshots/phase-h-past-due-warning.png",
  });
});
