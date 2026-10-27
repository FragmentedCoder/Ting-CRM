import { expect, test, type Browser, type Page } from "@playwright/test";
import { setUpAuthenticatorApp, signIn, toastWith, totp, watchForCspViolations } from "./helpers";

const CUSTOMER = "Fjordlys Energi A/S";

async function shot(page: Page, name: string) {
  await page.screenshot({ path: `e2e-results/screens/customers-${name}.png`, fullPage: true });
}

/** A link in the side menu; a string matches the whole name, a pattern its start. */
function menu(page: Page, name: string | RegExp) {
  return page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name, exact: typeof name === "string" });
}

/** Someone signed in, in a browser of their own, with an authenticator app set up. */
async function signedIn(browser: Browser, username: string, options: { clock?: boolean } = {}) {
  const context = await browser.newContext();
  // A clock the test can move on, for what the app checks once a minute.
  if (options.clock) await context.clock.install();
  const page = await context.newPage();
  await signIn(page, username);
  const secret = await setUpAuthenticatorApp(page);
  return { context, page, secret };
}

test("customers, from adding one to deleting it", async ({ browser }) => {
  const { context: bossContext, page: boss, secret: bossSecret } = await signedIn(browser, "e2e-boss");
  const violations = watchForCspViolations(boss);

  // An administrator adds the customer; it opens in the side menu.
  await menu(boss, "All customers").click();
  await expect(boss.getByRole("main").getByText("No customers yet.")).toBeVisible();
  await boss.getByRole("link", { name: "Add customer" }).click();
  await boss.getByLabel("Name").fill(CUSTOMER);
  await boss.getByLabel("CVR number (optional)").fill("1234 5678");
  await boss.getByLabel("Address").fill("Havnegade 4\n8000 Aarhus C");
  await boss.getByRole("button", { name: "Add customer" }).click();
  await expect(toastWith(boss, "with its own encryption key")).toBeVisible();
  await expect(boss.getByRole("heading", { name: CUSTOMER })).toBeVisible();
  await expect(boss.getByRole("main").getByText("12 34 56 78")).toBeVisible();
  await expect(boss.getByRole("button", { name: `Customer ${CUSTOMER}` })).toBeVisible();
  await expect(menu(boss, "Overview")).toHaveAttribute("aria-current", "page");

  // Its sites and contacts, then who works with it.
  await menu(boss, "Contacts & sites").click();
  await boss.getByRole("button", { name: "Add site" }).click();
  await boss.getByRole("dialog").getByLabel("Name").fill("Hovedkontor");
  await boss.getByRole("dialog").getByLabel("Address").fill("Havnegade 4");
  await boss.getByRole("button", { name: "Save site" }).click();
  await boss.getByRole("button", { name: "Add contact" }).click();
  const contact = boss.getByRole("dialog");
  await contact.getByLabel("Name").fill("Sigrid Holm");
  await contact.getByLabel("Role").fill("IT manager");
  await contact.getByLabel("Email").fill("sigrid@fjordlys.example");
  await contact.getByRole("button", { name: "Save contact" }).click();
  await expect(boss.getByText("sigrid@fjordlys.example")).toBeVisible();
  await shot(boss, "1-contacts");

  await menu(boss, "People").click();
  // Only technicians can be assigned: the auditor and the manager aren't offered.
  await expect(boss.getByRole("checkbox", { name: /Aud Auditor/ })).toHaveCount(0);
  await expect(boss.getByRole("checkbox", { name: /Maja Manager/ })).toHaveCount(0);
  await boss.getByRole("checkbox", { name: /Tor Tekniker/ }).check();
  await boss.getByRole("button", { name: "Save", exact: true }).click();
  await expect(toastWith(boss, "Who works with this customer is saved.")).toBeVisible();
  await menu(boss, "Overview").click();
  await expect(boss.getByRole("region", { name: "People on this customer" })).toContainText("Tor Tekniker");
  await shot(boss, "2-overview");

  // The technician finds the customer on Home and keeps its details and contacts
  // up to date, but doesn't choose how long its records are kept, its logo or who
  // works with it, and can't delete it.
  const { context: techContext, page: tech } = await signedIn(browser, "e2e-tech", { clock: true });
  await expect(tech.getByRole("heading", { name: "Your customers" })).toBeVisible();
  await tech.getByRole("main").getByRole("link", { name: CUSTOMER }).click();
  await expect(tech.getByRole("heading", { name: CUSTOMER })).toBeVisible();
  await menu(tech, "Customer settings").click();
  await tech.getByLabel("Address").fill("Havnegade 6\n8000 Aarhus C");
  await tech.getByRole("button", { name: "Save details" }).click();
  await expect(toastWith(tech, "Details saved.")).toBeVisible();
  await expect(tech.getByLabel("Keep its records for")).toHaveCount(0);
  await expect(tech.getByRole("heading", { name: "Logo" })).toHaveCount(0);
  await expect(tech.getByRole("button", { name: "Delete customer" })).toHaveCount(0);
  await shot(tech, "3-technician-settings");
  await menu(tech, "Contacts & sites").click();
  await tech.getByRole("button", { name: "Add contact" }).click();
  await tech.getByRole("dialog").getByLabel("Name").fill("Anders Vang");
  await tech.getByRole("dialog").getByRole("button", { name: "Save contact" }).click();
  await expect(tech.getByText("Anders Vang")).toBeVisible();
  await menu(tech, "People").click();
  await expect(tech.getByRole("checkbox")).toHaveCount(0);
  await expect(tech.getByRole("main")).toContainText("Tor Tekniker");

  // The manager sees every customer without being assigned, and runs it: its
  // details, how long its records are kept, its logo and who works with it. No
  // deleting, and no admin panel.
  const { context: managerContext, page: manager } = await signedIn(browser, "e2e-manager");
  await expect(manager.getByRole("heading", { name: "Customers", exact: true })).toBeVisible();
  await manager.getByRole("main").getByRole("link", { name: CUSTOMER }).click();
  await menu(manager, "Customer settings").click();
  await expect(manager.getByLabel("Keep its records for")).toBeVisible();
  await expect(manager.getByRole("heading", { name: "Logo" })).toBeVisible();
  await expect(manager.getByRole("button", { name: "Delete customer" })).toHaveCount(0);
  await menu(manager, "People").click();
  await expect(manager.getByRole("checkbox", { name: /Tor Tekniker/ })).toBeChecked();
  await expect(menu(manager, "Admin")).toHaveCount(0);
  await shot(manager, "4-manager-people");

  // Unassigned, the technician loses the customer at the next check, without
  // signing in again.
  await menu(boss, "People").click();
  await boss.getByRole("checkbox", { name: /Tor Tekniker/ }).uncheck();
  await boss.getByRole("button", { name: "Save", exact: true }).click();
  await expect(toastWith(boss, "Who works with this customer is saved.")).toBeVisible();
  await tech.clock.fastForward("01:05");
  await expect(toastWith(tech, `You no longer have access to ${CUSTOMER}.`)).toBeVisible();
  await expect(tech).toHaveURL(/\/customers$/);
  await expect(tech.getByRole("main").getByText("No customers yet.")).toBeVisible();
  await expect(tech.getByRole("button", { name: "Customer Choose a customer" })).toBeVisible();

  // Deleting the customer asks to confirm it's you, then takes everything with it.
  await menu(boss, "Customer settings").click();
  await expect(boss.getByLabel("Address")).toHaveValue("Havnegade 6\n8000 Aarhus C");
  await boss.getByRole("button", { name: "Delete customer" }).click();
  const confirm = boss.getByRole("dialog", { name: `Delete ${CUSTOMER}` });
  const forGood = confirm.getByRole("button", { name: "Delete for good" });
  await expect(forGood).toBeDisabled();
  await confirm.getByLabel("Type the customer's name to confirm").fill(CUSTOMER);
  await shot(boss, "5-delete");
  await forGood.click();
  const stepUp = boss.getByRole("dialog", { name: "Confirm it's you" });
  await stepUp.getByLabel("Code from your authenticator app").fill(totp(bossSecret, 1));
  await stepUp.getByRole("button", { name: "Verify code" }).click();
  await expect(toastWith(boss, "is deleted, and its key with it")).toBeVisible();
  await expect(boss.getByRole("main").getByText("No customers yet.")).toBeVisible();
  await expect(boss.getByRole("button", { name: "Customer Choose a customer" })).toBeVisible();
  await expect(toastWith(boss, "You no longer have access")).toHaveCount(0);

  expect(violations).toEqual([]);
  await bossContext.close();
  await managerContext.close();
  await techContext.close();
});
