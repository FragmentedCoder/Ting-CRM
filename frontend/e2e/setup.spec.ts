import { expect, test, type Page } from "@playwright/test";
import { addVirtualPasskey, PASSWORD, saveRecoveryCodes, watchForCspViolations } from "./helpers";

const SETUP_TOKEN = process.env.E2E_SETUP_TOKEN ?? "";

async function shot(page: Page, name: string) {
  await page.screenshot({ path: `e2e-results/screens/setup-${name}.png`, fullPage: true });
}

test("before setup, every page leads to the wizard", async ({ page }) => {
  for (const path of ["/", "/sign-in", "/sign-in/verify"]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/setup$/);
  }
});

test("the setup wizard, start to finish", async ({ page }) => {
  const violations = watchForCspViolations(page);
  await addVirtualPasskey(page);
  await page.goto("/setup");

  await expect(page.getByText("Step 1 of 9")).toBeVisible();
  await shot(page, "1-token");
  await page.getByLabel("Setup token").fill("AAAA-AAAA-AAAA-AAAA-AAAA-AAAA");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("alert")).toContainText("setup token isn't right");
  await page.getByLabel("Setup token").fill(SETUP_TOKEN.toLowerCase());
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByRole("heading", { name: "Company and server" })).toBeVisible();
  const address = process.env.TING_URL ?? "https://localhost";
  await expect(page.getByText(address, { exact: true })).toBeVisible();
  await shot(page, "2-company");
  await page.getByLabel("Company name").fill("Nordlys IT ApS");
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByRole("heading", { name: "Security settings" })).toBeVisible();
  await expect(page.getByLabel("Minimum password length")).toHaveValue("12");
  await page.getByLabel("Lock an account after").fill("8");
  await shot(page, "3-security");
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByRole("heading", { name: "Create the administrator" })).toBeVisible();
  await page.getByLabel("Full name").fill("Ingrid Admin");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Repeat password").fill(`${PASSWORD} typo`);
  await page.getByRole("button", { name: "Create administrator" }).click();
  await expect(page.getByRole("alert")).toContainText("don't match");
  await page.getByLabel("Repeat password").fill(PASSWORD);
  await shot(page, "4-administrator");
  await page.getByRole("button", { name: "Create administrator" }).click();

  // The breach check calls api.pwnedpasswords.com; if it can't be reached, the
  // wizard offers to go on without it, which is the path an offline server takes.
  const offline = page.getByRole("button", { name: "Continue without the check" });
  const protect = page.getByRole("heading", { name: "Protect the administrator" });
  await expect(offline.or(protect)).toBeVisible();
  if (await offline.isVisible()) await offline.click();

  await expect(protect).toBeVisible();
  await shot(page, "5-second-factor");
  await page.getByRole("button", { name: /Passkey or security key/ }).click();
  // The break-glass Administrator gets one code that works every time.
  await expect(page.getByRole("heading", { name: "Save your recovery code" })).toBeVisible();
  const codes = await saveRecoveryCodes(page);
  expect(codes).toHaveLength(1);
  expect(codes[0]).toMatch(/^([a-z2-9]{4}-){5}[a-z2-9]{4}$/);

  await expect(page.getByRole("heading", { name: "Save the recovery kit" })).toBeVisible();
  for (const key of ["Master key", "Backup key"]) {
    const value = page.locator("dt", { hasText: key }).locator("+ dd");
    await expect(value).toHaveText(/^([A-Z2-7]{4} ){12}[A-Z2-7]{4}$/);
  }
  await shot(page, "6-recovery-kit");
  const saved = page.getByRole("button", { name: "Continue" });
  await expect(saved).toBeDisabled();
  await page.getByLabel(/I have saved the recovery kit/).check();
  await saved.click();

  // Then where backups go, email and the certificate; each can wait.
  await expect(page.getByRole("heading", { name: "Where backups go" })).toBeVisible();
  await expect(page.getByText("Step 7 of 9")).toBeVisible();
  await expect(page.getByRole("radio", { name: /This server/ })).toBeChecked();
  await page.getByLabel("Every night at").selectOption("3");
  await shot(page, "7-backups");
  await page.getByRole("button", { name: "Save and continue" }).click();

  await expect(page.getByRole("heading", { name: "Email", exact: true })).toBeVisible();
  await expect(page.getByText("Step 8 of 9")).toBeVisible();
  await shot(page, "8-email");
  await page.getByRole("button", { name: "Set up later" }).click();

  await expect(page.getByRole("heading", { name: "Certificate" })).toBeVisible();
  await expect(page.getByText("Step 9 of 9")).toBeVisible();
  await expect(page.getByRole("radio", { name: /own certificate authority/ })).toBeChecked();
  await expect(page.getByRole("link", { name: "Download the root certificate" })).toBeVisible();
  await shot(page, "9-certificate");
  await page.getByRole("button", { name: "Save and finish setup" }).click();

  await expect(page.getByRole("heading", { name: "Welcome, Ingrid Admin" })).toBeVisible();
  await expect(page.getByText("Administrator", { exact: true })).toBeVisible();
  await shot(page, "10-done");
  expect(violations).toEqual([]);
});

test("after setup, the wizard is closed", async ({ page }) => {
  await page.goto("/setup");
  await expect(page).toHaveURL(/\/sign-in$/);
});
