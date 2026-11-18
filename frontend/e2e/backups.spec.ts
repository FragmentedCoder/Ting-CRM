import { expect, test } from "@playwright/test";
import { setUpAuthenticatorApp, signIn, toastWith, totp, watchForCspViolations } from "./helpers";

// Backups for real: the worker container backs up with restic to the backup volume,
// then restores the newest snapshot and checks it.
test("backups: back up, test a restore, and switch them off only after confirming", async ({ page }) => {
  test.setTimeout(180_000);
  const violations = watchForCspViolations(page);
  await signIn(page, "e2e-keeper");
  const secret = await setUpAuthenticatorApp(page);
  const menu = page.getByRole("navigation", { name: "Main" });

  await menu.getByRole("link", { name: "Admin", exact: true }).click();
  await menu.getByRole("link", { name: "Backups", exact: true }).click();
  await expect(page.getByRole("heading", { name: "How it stands" })).toBeVisible();
  await expect(page.getByRole("radio", { name: /This server/ })).toBeChecked();

  await page.getByRole("button", { name: "Back up now" }).click();
  await expect(toastWith(page, /Backup to this server: .* backed up/)).toBeVisible({ timeout: 90_000 });
  await page.getByRole("button", { name: "Test a restore now" }).click();
  await expect(toastWith(page, /Restore test to this server: Restored snapshot .* check out/)).toBeVisible({
    timeout: 90_000,
  });
  const runs = page.getByRole("region", { name: "Recent runs" });
  // The list reloads once the toast has shown; on a slow runner that takes a moment.
  await expect(runs.getByRole("row", { name: /Restore test/ }).first()).toContainText("OK", { timeout: 20_000 });
  await page.screenshot({ path: "e2e-results/screens/backups-1-page.png", fullPage: true });

  // Server health reports both; a backup on this server only is a warning.
  await menu.getByRole("link", { name: "Server health", exact: true }).click();
  await expect(page.getByText(/Backed up .* to this server\. A backup on the same server/)).toBeVisible();
  await expect(page.getByText(/Restored and checked .* audit log entries\./)).toBeVisible();

  // Switching them off is a change to where backups go: it asks to confirm it's you.
  await menu.getByRole("link", { name: "Backups", exact: true }).click();
  // A second place shows its own fields; switching backups off removes every place.
  await page.getByRole("button", { name: "Add another place" }).click();
  await expect(page.getByLabel("Server", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Remove place 2" }).click();
  await page.getByRole("button", { name: "Remove it" }).click();
  await expect(page.getByText("Backups are off: nothing is being backed up.")).toBeVisible();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const stepUp = page.getByRole("dialog", { name: "Confirm it's you" });
  await stepUp.getByLabel("Code from your authenticator app").fill(totp(secret, 1));
  await stepUp.getByRole("button", { name: "Verify code" }).click();
  await expect(toastWith(page, "Backup settings saved.")).toBeVisible();
  await expect(page.getByText("None: backups are off")).toBeVisible();
  await expect(page.getByRole("button", { name: "Back up now" })).toBeDisabled();

  expect(violations).toEqual([]);
});
