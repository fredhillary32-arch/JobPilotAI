import { expect, test, type Page, type TestInfo } from "@playwright/test";

const testEmail = process.env.JOBPILOT_TEST_EMAIL;
const testPassword = process.env.JOBPILOT_TEST_PASSWORD;
const testProfileId = process.env.JOBPILOT_TEST_PROFILE_ID;
const otherTestEmail = process.env.JOBPILOT_OTHER_TEST_EMAIL;
const otherTestPassword = process.env.JOBPILOT_OTHER_TEST_PASSWORD;
const otherTestProfileId = process.env.JOBPILOT_OTHER_TEST_PROFILE_ID;
const browserDiagnostics = new WeakMap<Page, { captured: string[]; unexpected: string[] }>();

test.beforeEach(async ({ page }) => {
  const diagnostics = { captured: [] as string[], unexpected: [] as string[] };
  browserDiagnostics.set(page, diagnostics);
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const path = new URL(message.location().url || "http://localhost").pathname;
    const status = message.text().match(/status of (\d{3})/)?.[1] ?? "unknown";
    const expectedUnauthenticatedResponse = status === "401" &&
      ["/api/v1/auth/session", "/api/v1/auth/login", "/api/v1/candidate-profiles"].includes(path);
    const summary = `console error: ${path} HTTP ${status}`;
    diagnostics.captured.push(summary);
    if (!expectedUnauthenticatedResponse) diagnostics.unexpected.push(summary);
  });
  page.on("pageerror", (error) => {
    const summary = `page error: ${error.name}`;
    diagnostics.captured.push(summary);
    diagnostics.unexpected.push(summary);
  });
  page.on("requestfailed", (request) => {
    const url = new URL(request.url());
    const summary = `request failed: ${request.method()} ${url.pathname}`;
    diagnostics.captured.push(summary);
    diagnostics.unexpected.push(summary);
  });
});

test.afterEach(async ({ page }, testInfo) => {
  const diagnostics = browserDiagnostics.get(page) ?? { captured: [], unexpected: [] };
  if (diagnostics.captured.length > 0) {
    await testInfo.attach("browser-diagnostics", {
      body: diagnostics.captured.join("\n"),
      contentType: "text/plain",
    });
  }
  expect(diagnostics.unexpected, "unexpected sanitized browser diagnostics").toEqual([]);
});

test("renders a responsive sign-in form and enforces required fields", async ({ page }) => {
  const sessionResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith("/api/v1/auth/session"),
  );
  await page.goto("/");
  expect((await sessionResponse).status()).toBe(401);
  await expect(page.getByRole("heading", { name: "Sign in to JobPilot" })).toBeVisible();
  await expect(page.getByLabel("Email address")).toBeVisible();
  await expect(page.getByLabel("Password")).toBeVisible();

  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to JobPilot" })).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(hasHorizontalOverflow).toBe(false);
});

test("rejects invalid credentials with a safe message and keeps protected APIs private", async ({ page }) => {
  await page.goto("/");
  const email = `playwright-${process.pid}-${Date.now()}@invalid.example`;
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill("This-is-not-a-real-account-4938");

  const loginResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith("/api/v1/auth/login"),
  );
  await page.getByRole("button", { name: "Sign in" }).click();
  expect((await loginResponse).status()).toBe(401);
  await expect(page.getByRole("alert")).toHaveText(
    "Sign-in was unsuccessful. Check your credentials and try again.",
  );
  await expect(page.getByLabel("Password")).toHaveValue("");

  const protectedResponse = await page.evaluate(async () => {
    const response = await fetch("/api/v1/candidate-profiles", { credentials: "same-origin" });
    return response.status;
  });
  expect(protectedResponse).toBe(401);
  await expect(page.getByRole("heading", { name: "Sign in to JobPilot" })).toBeVisible();
});

test("keeps the loading state while session restoration is delayed", async ({ page }) => {
  let releaseResponse!: () => void;
  const responseGate = new Promise<void>((resolve) => {
    releaseResponse = resolve;
  });
  await page.route("**/api/v1/auth/session", async (route) => {
    await responseGate;
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Authentication required." }),
    });
  });

  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("Restoring your secure session");
  releaseResponse();
  await expect(page.getByRole("heading", { name: "Sign in to JobPilot" })).toBeVisible();
});

test("prevents duplicate login requests while a submission is pending", async ({ page }) => {
  let releaseResponse!: () => void;
  const responseGate = new Promise<void>((resolve) => {
    releaseResponse = resolve;
  });
  let loginRequests = 0;
  await page.route("**/api/v1/auth/pre-auth-csrf", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ csrf_token: "playwright-only-challenge" }),
    }),
  );
  await page.route("**/api/v1/auth/login", async (route) => {
    loginRequests += 1;
    await responseGate;
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Invalid email or password." }),
    });
  });

  await page.goto("/");
  await page.getByLabel("Email address").fill("playwright-pending@invalid.example");
  await page.getByLabel("Password").fill("Not-a-real-account-4938");
  await page.getByRole("button", { name: "Sign in" }).click();
  const submitButton = page.getByRole("button", { name: "Signing in…" });
  await expect(submitButton).toBeDisabled();
  await submitButton.evaluate((button) => (button as HTMLButtonElement).click());
  expect(loginRequests).toBe(1);
  releaseResponse();
  await expect(page.getByRole("alert")).toHaveText(
    "Sign-in was unsuccessful. Check your credentials and try again.",
  );
});

test("persists a dedicated test session across reload and revokes it on logout", async ({ page }, testInfo: TestInfo) => {
  test.skip(
    !testEmail || !testPassword || !testProfileId,
    "Set dedicated JOBPILOT_TEST_EMAIL, JOBPILOT_TEST_PASSWORD, and JOBPILOT_TEST_PROFILE_ID values locally.",
  );

  await page.goto("/");
  await page.getByLabel("Email address").fill(testEmail!);
  await page.getByLabel("Password").fill(testPassword!);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Start with your profile" })).toBeVisible();

  await page.getByLabel("Candidate profile ID").fill(testProfileId!);
  await page.getByRole("button", { name: "Open profile" }).click();
  await expect(page.getByText("Connecting to your local JobPilot workspace")).toBeHidden();
  await expect(page.getByRole("button", { name: "Overview" })).toBeVisible();

  await page.reload();
  await expect(page.getByRole("button", { name: "Overview" })).toBeVisible();
  const sessionStatus = await page.evaluate(async () =>
    (await fetch("/api/v1/auth/session", { credentials: "same-origin" })).status,
  );
  expect(sessionStatus).toBe(200);
  await page.evaluate(() => history.pushState({ smokeTest: true }, "", "#protected-workspace"));

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to JobPilot" })).toBeVisible();
  const revokedSessionStatus = await page.evaluate(async () =>
    (await fetch("/api/v1/auth/session", { credentials: "same-origin" })).status,
  );
  expect(revokedSessionStatus).toBe(401);

  await page.goBack();
  await expect(page.getByRole("heading", { name: "Sign in to JobPilot" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Overview" })).toHaveCount(0);
  const backNavigationStatus = await page.evaluate(async () =>
    (await fetch("/api/v1/candidate-profiles", { credentials: "same-origin" })).status,
  );
  expect(backNavigationStatus).toBe(401);

  await testInfo.attach("auth-browser-check", {
    body: "Dedicated account session persisted after reload, logout revoked the session, and back navigation remained unauthorized.",
    contentType: "text/plain",
  });
});

test("prevents two dedicated accounts from reading each other's profiles", async ({ page }) => {
  test.skip(
    !testEmail || !testPassword || !testProfileId ||
      !otherTestEmail || !otherTestPassword || !otherTestProfileId,
    "Set dedicated account and profile values for both test users locally.",
  );

  await page.goto("/");
  await page.getByLabel("Email address").fill(testEmail!);
  await page.getByLabel("Password").fill(testPassword!);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Start with your profile" })).toBeVisible();

  const firstOwnProfileStatus = await page.evaluate(async (profileId) =>
    (await fetch(`/api/v1/candidate-profiles/${encodeURIComponent(profileId)}`, {
      credentials: "same-origin",
    })).status,
  testProfileId!);
  expect(firstOwnProfileStatus).toBe(200);
  const firstForeignProfileStatus = await page.evaluate(async (profileId) =>
    (await fetch(`/api/v1/candidate-profiles/${encodeURIComponent(profileId)}`, {
      credentials: "same-origin",
    })).status,
  otherTestProfileId!);
  expect([403, 404]).toContain(firstForeignProfileStatus);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to JobPilot" })).toBeVisible();
  await page.getByLabel("Email address").fill(otherTestEmail!);
  await page.getByLabel("Password").fill(otherTestPassword!);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Start with your profile" })).toBeVisible();

  const secondOwnProfileStatus = await page.evaluate(async (profileId) =>
    (await fetch(`/api/v1/candidate-profiles/${encodeURIComponent(profileId)}`, {
      credentials: "same-origin",
    })).status,
  otherTestProfileId!);
  expect(secondOwnProfileStatus).toBe(200);
  const secondForeignProfileStatus = await page.evaluate(async (profileId) =>
    (await fetch(`/api/v1/candidate-profiles/${encodeURIComponent(profileId)}`, {
      credentials: "same-origin",
    })).status,
  testProfileId!);
  expect([403, 404]).toContain(secondForeignProfileStatus);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to JobPilot" })).toBeVisible();
});
