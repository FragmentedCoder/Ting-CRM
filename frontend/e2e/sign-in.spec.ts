import { expect, test } from "@playwright/test";
import {
  START_HEADING,
  addVirtualPasskey,
  saveRecoveryCodes,
  signIn,
  signOut,
  totp,
  watchForCspViolations,
} from "./helpers";

test("a page that needs sign-in sends you to sign in", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/sign-in$/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("a wrong password is refused with a plain message", async ({ page }) => {
  await signIn(page, "e2e-wrong", "not the right password at all");
  await expect(page.getByRole("alert")).toContainText("Sign-in failed");
  await expect(page).toHaveURL(/\/sign-in$/);
  await expect(page.getByLabel("Password")).toHaveValue("");
});

test("first sign-in with a passkey, then signing in with it", async ({ page }) => {
  const violations = watchForCspViolations(page);
  await addVirtualPasskey(page);

  await signIn(page, "e2e-passkey");
  await expect(page).toHaveURL(/\/sign-in\/set-up$/);
  await page.getByRole("button", { name: /Passkey or security key/ }).click();

  const codes = await saveRecoveryCodes(page);
  expect(codes).toHaveLength(10);
  await expect(page.getByRole("heading", { name: START_HEADING })).toBeVisible();

  await signOut(page);
  await signIn(page, "e2e-passkey");
  await expect(page).toHaveURL(/\/sign-in\/verify$/);
  await page.getByRole("button", { name: "Use passkey or security key" }).click();
  await expect(page.getByRole("heading", { name: START_HEADING })).toBeVisible();

  expect(violations).toEqual([]);
});

test("first sign-in with an authenticator app, then a recovery code, then the app", async ({
  page,
}) => {
  const violations = watchForCspViolations(page);

  await signIn(page, "e2e-app");
  await page.getByRole("button", { name: /Authenticator app/ }).click();
  await expect(page.getByRole("img", { name: /QR code/ })).toBeVisible();
  const secret = (await page.locator(".secret").textContent()) ?? "";

  await page.getByLabel("6-digit code").fill(totp(secret));
  await page.getByRole("button", { name: "Confirm" }).click();
  const codes = await saveRecoveryCodes(page);
  await signOut(page);

  await signIn(page, "e2e-app");
  await page.getByRole("button", { name: "Use a recovery code instead" }).click();
  await page.getByLabel("Recovery code").fill(codes[0]);
  await page.getByRole("button", { name: "Use recovery code" }).click();
  await expect(page.getByRole("heading", { name: START_HEADING })).toBeVisible();
  await signOut(page);

  await signIn(page, "e2e-app");
  // The code field has the focus, so the code can be typed straight away.
  await expect(page.getByLabel("Code from your authenticator app")).toBeFocused();
  await page.getByLabel("Code from your authenticator app").fill(totp(secret, 1));
  await page.getByRole("button", { name: "Verify code" }).click();
  await expect(page.getByRole("heading", { name: START_HEADING })).toBeVisible();

  expect(violations).toEqual([]);
});

test("a wrong code shows a message and keeps you on the page", async ({ page }) => {
  await signIn(page, "e2e-app");
  await page.getByLabel("Code from your authenticator app").fill("000000");
  await page.getByRole("button", { name: "Verify code" }).click();
  await expect(page.getByRole("alert")).toContainText("didn't work");
  await expect(page).toHaveURL(/\/sign-in\/verify$/);
});

test("the security headers are sent", async ({ request }) => {
  const response = await request.get("/sign-in");
  const headers = response.headers();
  expect(headers["x-frame-options"]).toBe("DENY");
  expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(headers["strict-transport-security"]).toBeTruthy();
  const html = await response.text();
  expect(html).toContain('http-equiv="content-security-policy"');
  expect(html).toContain("script-src 'self' 'sha256-");
});
