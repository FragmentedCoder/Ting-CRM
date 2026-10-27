import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import { customSwatch } from "../src/lib/colours";
import { setUpAuthenticatorApp, signIn, toastWith, totp, watchForCspViolations } from "./helpers";

const BJORN_PASSWORD = "bjørns egen lange adgangssætning";

/** A section link in the side menu (not a breadcrumb of the same name). */
function adminMenu(page: Page, name: string) {
  return page.getByRole("navigation", { name: "Main" }).getByRole("link", { name, exact: true });
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: `e2e-results/screens/admin-${name}.png`, fullPage: true });
}

test("the admin panel, from adding a user to their first sign-in", async ({ browser }) => {
  const adminContext = await browser.newContext();
  const admin = await adminContext.newPage();
  const violations = watchForCspViolations(admin);

  await signIn(admin, "e2e-admin");
  await expect(admin).toHaveURL(/\/sign-in\/set-up$/);
  const adminSecret = await setUpAuthenticatorApp(admin);
  await admin.getByRole("link", { name: "Admin", exact: true }).click();

  // Users: the list, then adding Bjørn as a technician.
  await expect(admin.getByRole("heading", { name: "Users" })).toBeVisible();
  await expect(admin.getByRole("row", { name: /Ingrid Admin/ })).toContainText("Break-glass");
  await shot(admin, "1-users");
  await admin.getByRole("link", { name: "Add user" }).click();
  await admin.getByLabel("Display name").fill("Bjørn Havn");
  await admin.getByLabel("Username").fill("bjorn");
  await admin.getByRole("checkbox", { name: /^Technician\b/ }).check();
  await shot(admin, "2-add-user");
  await admin.getByRole("button", { name: "Add user" }).click();
  const temporary = (await admin.getByLabel("Temporary password").textContent()) ?? "";
  expect(temporary).toMatch(/^([a-z2-9]{4}-){3}[a-z2-9]{4}$/);
  await shot(admin, "3-temporary-password");
  await admin.getByRole("link", { name: "Open user" }).click();
  await expect(admin.getByText("Awaiting first sign-in")).toBeVisible();

  // Bjørn, in his own browser: temporary password, his own password, multifactor.
  const bjornContext = await browser.newContext();
  const bjorn = await bjornContext.newPage();
  await signIn(bjorn, "bjorn", temporary);
  await expect(bjorn).toHaveURL(/\/sign-in\/new-password$/);
  await shot(bjorn, "4-new-password");
  await bjorn.getByLabel("New password", { exact: true }).fill(BJORN_PASSWORD);
  await bjorn.getByLabel("Repeat password").fill(BJORN_PASSWORD);
  await bjorn.getByRole("button", { name: "Save password" }).click();

  // The breach check calls out to the internet; an offline run gets a clear refusal.
  const setUp = bjorn.getByRole("heading", { name: "Set up multifactor" });
  await expect(setUp.or(bjorn.getByRole("alert"))).toBeVisible();
  test.skip(!(await setUp.isVisible()), "the breach check service could not be reached");

  const bjornSecret = await setUpAuthenticatorApp(bjorn);
  await expect(bjorn.getByText("Technician", { exact: true })).toBeVisible();
  await expect(bjorn.getByRole("link", { name: "Admin", exact: true })).toHaveCount(0);
  await bjorn.goto("/admin/users");
  await expect(bjorn.getByText("You don't have access to the admin panel.")).toBeVisible();

  // Back to the administrator: Bjørn is active now. End his session: his browser
  // goes to the sign-in page and says why.
  await admin.reload();
  await expect(admin.locator(".tags").getByText("Active", { exact: true })).toBeVisible();
  await expect(admin.locator("li", { hasText: "Authenticator app" })).toBeVisible();
  await shot(admin, "5-user");
  await admin.getByRole("button", { name: /^End session/ }).click();
  await expect(admin.getByText("Not signed in anywhere.")).toBeVisible();
  await bjorn.getByRole("link", { name: /your account/ }).click();
  await expect(bjorn).toHaveURL(/\/sign-in$/);
  await expect(toastWith(bjorn, "An administrator signed you out.")).toBeVisible();
  await shot(bjorn, "6-signed-out-toast");
  await bjorn.getByRole("button", { name: "Dismiss" }).click();
  await expect(toastWith(bjorn, "An administrator signed you out.")).toHaveCount(0);

  // He signs in again with his app; then the row menu resets his multifactor.
  await signIn(bjorn, "bjorn", BJORN_PASSWORD);
  await bjorn.getByLabel("Code from your authenticator app").fill(totp(bjornSecret, 1));
  await bjorn.getByRole("button", { name: "Verify code" }).click();
  await expect(bjorn.getByRole("heading", { name: /Welcome/ })).toBeVisible();
  await adminMenu(admin, "Users").click();
  await admin.getByRole("button", { name: "Actions for Bjørn Havn" }).click();
  // The visible screen only: a full-page capture resizes the window under the open menu.
  await admin.screenshot({ path: "e2e-results/screens/admin-7-row-menu.png" });
  await admin.getByRole("menuitem", { name: "Reset multifactor…" }).click();
  await admin.getByRole("dialog").getByRole("button", { name: "Reset multifactor" }).click();
  await expect(toastWith(admin, "Bjørn Havn sets up multifactor again")).toBeVisible();
  await expect(admin.getByRole("row", { name: /Bjørn Havn/ })).toContainText("Not yet");
  await bjorn.reload();
  await expect(bjorn).toHaveURL(/\/sign-in$/);
  await expect(toastWith(bjorn, /reset your multifactor authentication/)).toBeVisible();

  // Security: a change is saved; an allowlist that shuts this browser out is refused.
  await adminMenu(admin, "Security").click();
  await expect(admin.getByRole("switch", { name: "Required for everyone" })).toBeChecked();
  await admin.getByLabel("Keep it locked for").fill("20");
  await admin.getByRole("button", { name: "Save settings" }).click();
  await expect(toastWith(admin, "Security settings saved.")).toBeVisible();

  // Lowering security asks to confirm it's you, however recent the sign-in.
  const everyone = admin.getByRole("switch", { name: /Required for everyone/ });
  await everyone.uncheck();
  await admin.getByRole("button", { name: "Save settings" }).click();
  const confirm = admin.getByRole("dialog", { name: "Confirm it's you" });
  await expect(confirm).toBeVisible();
  await expect(confirm.getByLabel("Code from your authenticator app")).toBeFocused();
  await shot(admin, "8-step-up");
  await confirm.getByLabel("Code from your authenticator app").fill(totp(adminSecret, 1));
  await confirm.getByRole("button", { name: "Verify code" }).click();
  await expect(confirm).toBeHidden();
  await admin.reload();
  await expect(everyone).not.toBeChecked();
  // Raising it again needs no new confirmation.
  await everyone.check();
  await admin.getByRole("button", { name: "Save settings" }).click();
  await expect(admin.getByRole("dialog", { name: "Confirm it's you" })).toBeHidden();
  await admin.reload();
  await expect(everyone).toBeChecked();
  await admin.getByRole("switch", { name: /Only open the admin panel/ }).check();
  await admin.getByLabel("Admin panel allowlist").fill("10.99.0.0/24");
  await admin.getByRole("button", { name: "Save settings" }).click();
  await expect(admin.getByRole("alert")).toContainText("lock you out");
  await expect(admin.getByText("sudo ting admin reset-allowlist")).toBeVisible();
  await shot(admin, "8-security");
  await admin.reload();

  // Branding: a new site name and company name show at once.
  await adminMenu(admin, "Branding").click();
  await admin.getByLabel("Site name").fill("Nordlys CRM");
  await admin.getByLabel("Tag line").fill("Kunder ved fjorden.");
  await admin.getByLabel("Company name").fill("Nordlys IT A/S");
  await admin.getByRole("button", { name: "Save", exact: true }).click();
  await expect(toastWith(admin, "Branding saved.")).toBeVisible();
  // However many have piled up, at most three toasts show at once.
  const shown = admin.getByRole("region", { name: "Notifications" }).getByRole("listitem");
  expect(await shown.count()).toBeLessThanOrEqual(3);

  // A custom colour: one too light to read in light mode is shaded just enough.
  const primaryPicker = admin.getByRole("group", { name: "Primary colour" });
  await primaryPicker.getByRole("radio", { name: "Custom" }).check();
  await admin.getByLabel("Your colour").fill("#ffd700");
  const gold = customSwatch("#FFD700", "primary");
  await expect(primaryPicker).toContainText(`Þing uses ${gold.light} in light mode`);
  await shot(admin, "9b-custom-colour");
  await admin.getByRole("button", { name: "Save colours" }).click();
  await expect(toastWith(admin, "Colours saved.")).toBeVisible();
  await expect
    .poll(() => admin.evaluate(() => document.documentElement.style.getPropertyValue("--link")))
    .toBe(gold.light);
  await primaryPicker.getByRole("radio", { name: "Fjord" }).check();
  await admin.getByRole("button", { name: "Save colours" }).click();
  await expect
    .poll(() => admin.evaluate(() => document.documentElement.style.getPropertyValue("--link")))
    .toBe("");
  // The menu's head: the name and the tag line under it. Which Þing this is (a
  // development build here) is the menu's last line, just above the account.
  const side = admin.getByRole("complementary", { name: "Side menu" });
  const menuHead = side.locator(".side-head");
  await expect(menuHead).toContainText("Nordlys CRM");
  await expect(menuHead).toContainText("Kunder ved fjorden.");
  await expect(menuHead).not.toContainText(/\d+\.\d+\.\d+/);
  const version = side.locator(".version");
  await expect(version).toBeInViewport();
  await expect(version).toContainText(/Þing \d+\.\d+\.\d+-dev/);
  const below = await side.locator(".you").boundingBox();
  expect((await version.boundingBox())!.y).toBeLessThan(below!.y);
  await expect(admin).toHaveTitle(/Nordlys CRM/);
  await shot(admin, "9-branding");

  // Server health: every check runs, and the audit chain is intact; the daily
  // timestamp (it needs the internet) is asked for here too.
  await adminMenu(admin, "Server health").click();
  await expect(admin.getByText(/Chain intact: \d+ entries checked/)).toBeVisible();
  await expect(admin.getByText("Encrypted, and every page passed")).toBeVisible();
  await expect(admin.getByText("Running.", { exact: true })).toBeVisible();
  await expect(admin.locator(".check-label .is-ok").first()).toBeVisible();
  await expect(admin.getByRole("button", { name: "Timestamp now" })).toBeVisible();
  await expect(admin.getByText("Timestamp authority", { exact: true })).toBeVisible();
  await shot(admin, "10-health");

  // Audit log: one line on the chain, filters work, and the export downloads.
  await adminMenu(admin, "Audit log").click();
  await expect(admin.getByText(/The chain is intact: all \d+ entries check\s+out/)).toBeVisible();
  await expect(admin.getByRole("button", { name: "Timestamp now" })).toHaveCount(0);
  await admin.getByLabel("What").selectOption("admin.*");
  await admin.getByRole("button", { name: "Show" }).click();
  // Times are ISO 8601, in UTC.
  await expect(admin.locator("tbody td:nth-child(2)").first()).toHaveText(
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/,
  );
  const actions = admin.locator("tbody td:nth-child(4)");
  await expect(actions.first()).toContainText("admin.");
  for (const action of await actions.allTextContents()) expect(action).toMatch(/^admin\./);
  await shot(admin, "11-audit");
  const [download] = await Promise.all([
    admin.waitForEvent("download"),
    admin.getByRole("link", { name: "Export CSV" }).click(),
  ]);
  const csv = await readFile((await download.path()) ?? "", "utf8");
  // CSV rows end in CRLF (RFC 4180).
  expect(csv.split("\r\n")[0]).toBe(
    "seq,occurred_at,actor_id,actor_name,action,target_type,target_id,ip,details,hash",
  );
  expect(csv).toContain("admin.user_created");

  // Your account: light or dark and the colours apply at once and are kept;
  // the button in the side menu switches between light and dark too.
  const link = () =>
    admin.evaluate(() => document.documentElement.style.getPropertyValue("--link"));
  await admin.getByRole("link", { name: "Your account" }).click();
  // In the app the change is instant: the slow fade is for the sign-in screens.
  const fades = () => admin.evaluate(() => (window as unknown as { fades: number }).fades);
  await admin.evaluate(() => {
    const counted = window as unknown as { fades: number };
    counted.fades = 0;
    const fade = document.startViewTransition.bind(document);
    document.startViewTransition = (update) => {
      counted.fades++;
      return fade(update);
    };
  });
  await admin.getByRole("radio", { name: "Dark", exact: true }).check();
  await expect(admin.locator("html")).toHaveAttribute("data-theme", "dark");
  await admin.getByRole("radio", { name: "Pine" }).check();
  await expect.poll(link).toBe("#5FBF84");
  await shot(admin, "12-account-dark");
  await admin.getByRole("button", { name: "Switch to light mode" }).click();
  await expect(admin.locator("html")).toHaveAttribute("data-theme", "light");
  await expect.poll(link).toBe("#2F6B47");
  expect(await fades()).toBe(0);
  await admin.reload();
  await expect(admin.locator("html")).toHaveAttribute("data-theme", "light");
  await expect.poll(link).toBe("#2F6B47");
  await admin.getByRole("radio", { name: "Same as this device" }).check();
  await admin.getByRole("radio", { name: "Site's (Fjord)" }).check();
  await expect(admin.locator("html")).not.toHaveAttribute("data-theme", /.+/);
  await expect.poll(link).toBe("");

  expect(violations).toEqual([]);
  await adminContext.close();
  await bjornContext.close();
});
