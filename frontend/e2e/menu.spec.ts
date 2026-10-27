import { expect, test, type Page } from "@playwright/test";
import { setUpAuthenticatorApp, signIn, watchForCspViolations } from "./helpers";

// The side menu with a few (fictional) customers, as an administrator, as a
// technician on some of them and as an auditor. Screenshots go to
// e2e-results/screens.

interface Created {
  id: number;
}

interface Detail extends Created {
  assignable: { id: number; username: string }[];
}

/** Calls the API as the page's signed-in user, CSRF token included. */
async function call<T>(page: Page, method: string, path: string, body?: unknown): Promise<T> {
  return page.evaluate(
    async ({ method, path, body }) => {
      const session = await (await fetch("/api/auth/session")).json();
      const response = await fetch(`/api${path}`, {
        method,
        headers: { "Content-Type": "application/json", "X-CSRF-Token": session.csrf_token },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`${method} ${path}: ${response.status} ${await response.text()}`);
      return response.json();
    },
    { method, path, body },
  );
}

async function addCustomer(page: Page, name: string, cvr: string, contacts: string[][], sites: string[]) {
  const customer = await call<Detail>(page, "POST", "/customers", { name, cvr, address: "Havnegade 4\n8000 Aarhus C" });
  for (const [contact, role, email] of contacts) {
    await call(page, "POST", `/customers/${customer.id}/contacts`, { name: contact, role, email });
  }
  for (const site of sites) await call(page, "POST", `/customers/${customer.id}/sites`, { name: site });
  return customer;
}

function menu(page: Page) {
  return page.getByRole("navigation", { name: "Main" });
}

test("the side menu, with customers", async ({ browser }) => {
  test.setTimeout(240_000); // the page tour takes about a hundred screenshots
  const shotsOf = (page: Page, theme: string) => (name: string) =>
    page.screenshot({ path: `e2e-results/screens/menu-${name}-${theme}.png` });

  const metteContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const mette = await metteContext.newPage();
  const violations = watchForCspViolations(mette);
  await signIn(mette, "e2e-mette");
  await setUpAuthenticatorApp(mette);
  // Þing starts light; following the device lets the tour show both themes.
  await call(mette, "PATCH", "/account", { theme: "system" });

  const fjordlys = await addCustomer(mette, "Fjordlys Energi A/S", "12345678",
    [["Sigrid Holm", "IT manager", "sigrid@fjordlys.example"], ["Anders Vang", "CISO", "anders@fjordlys.example"]],
    ["Hovedkontor", "Datacenter Aarhus"]);
  const nordhavn = await addCustomer(mette, "Nordhavn Logistik ApS", "87654321",
    [["Lise Kjær", "Head of IT", "lise@nordhavn.example"]], ["Lager Køge"]);
  const solvbjerg = await addCustomer(mette, "Sølvbjerg Kommune", "29189900", [], []);
  const bob = fjordlys.assignable.find((p) => p.username === "e2e-bob")!.id;
  for (const customer of [fjordlys, nordhavn]) {
    await call(mette, "PUT", `/customers/${customer.id}/assignments`, { people: [bob] });
  }

  // The administrator: the customer picked in the menu, and its sections.
  for (const theme of ["light", "dark"] as const) {
    await mette.emulateMedia({ colorScheme: theme });
    const shot = shotsOf(mette, theme);
    await mette.goto(`/customers/${fjordlys.id}`);
    await expect(mette.getByRole("heading", { name: "Fjordlys Energi A/S" })).toBeVisible();
    for (const name of ["Overview", "Contacts & sites", "People", "Customer settings"]) {
      await expect(menu(mette).getByRole("link", { name, exact: true })).toBeVisible();
    }
    await shot("1-customer");

    // The picker is under its button the moment it opens, never anywhere else
    // first: measured in the same step as the click.
    const opened = await mette.evaluate(() => {
      const button = document.querySelector<HTMLButtonElement>("nav[aria-label=Main] button[popovertarget]")!;
      button.click();
      const panel = document.getElementById(button.getAttribute("popovertarget")!)!;
      return { button: button.getBoundingClientRect().toJSON(), panel: panel.getBoundingClientRect().toJSON() };
    });
    expect(opened.panel.top).toBeGreaterThan(opened.button.bottom);
    expect(opened.panel.left).toBe(opened.button.left);
    expect(opened.panel.right).toBe(opened.button.right);
    await expect(mette.getByRole("dialog", { name: "Choose a customer" })).toBeVisible();
    await shot("2-picker");
    await mette.keyboard.press("Escape");

    await mette.goto(`/customers/${fjordlys.id}/people`);
    await expect(mette.getByRole("checkbox", { name: /Bob Bager/ })).toBeChecked();
    await shot("3-people");
  }

  // A long menu (a customer's sections and Admin's) scrolls on its own:
  // the page you're on and Sign out both stay in view.
  await mette.goto("/admin/audit");
  await expect(menu(mette).getByRole("link", { name: "Audit log" })).toBeInViewport();
  await expect(mette.getByRole("button", { name: "Sign out" })).toBeInViewport();
  // Also when the session answers slowly, so the menu comes after the page has
  // loaded (SvelteKit's afterNavigate doesn't run for it then).
  await mette.route("**/api/auth/session", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue();
  });
  await mette.goto("/admin/audit");
  await expect(menu(mette).getByRole("link", { name: "Audit log" })).toBeInViewport();
  await mette.unroute("**/api/auth/session");

  // Opening a customer's page fetches the customer once: what loading it changes
  // (the menu's list, the customer itself) doesn't start it again.
  const loads: string[] = [];
  mette.on("request", (request) => {
    if (new URL(request.url()).pathname === `/api/customers/${fjordlys.id}`) loads.push(request.url());
  });
  await mette.goto(`/customers/${fjordlys.id}/people`);
  await expect(mette.getByRole("heading", { name: "Who works with this customer" })).toBeVisible();
  await mette.waitForTimeout(1500);
  expect(loads).toHaveLength(1);

  // Opening Admin pushes nothing up: the menu runs from the top. Clicked again on
  // its own pages, a group folds away and opens again.
  await mette.goto(`/customers/${fjordlys.id}`);
  await expect(menu(mette).getByRole("link", { name: "Contacts & sites" })).toBeVisible();
  const adminItem = menu(mette).getByRole("link", { name: "Admin", exact: true });
  const usersItem = menu(mette).getByRole("link", { name: "Users", exact: true });
  const before = await adminItem.boundingBox();
  await adminItem.click();
  await expect(mette.getByRole("heading", { name: "Users" })).toBeVisible();
  await expect(adminItem).toHaveAttribute("aria-expanded", "true");
  expect((await adminItem.boundingBox())?.y).toBe(before?.y);
  await adminItem.click();
  await expect(adminItem).toHaveAttribute("aria-expanded", "false");
  await expect(usersItem).toBeHidden();
  await adminItem.click();
  await expect(usersItem).toBeVisible();
  await expect(mette).toHaveURL(/\/admin\/users$/);

  // At phone width the menu slides in over the page.
  // Without the slide, so the screenshot shows the menu fully open.
  await mette.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
  await mette.setViewportSize({ width: 390, height: 844 });
  await mette.goto(`/customers/${fjordlys.id}/contacts`);
  await mette.getByRole("button", { name: "Open the menu" }).click();
  await expect(menu(mette).getByRole("link", { name: "Overview" })).toBeVisible();
  await shotsOf(mette, "light")("5-phone");
  await mette.keyboard.press("Escape");
  await expect(menu(mette).getByRole("link", { name: "Overview" })).toBeHidden();

  // Bob, a technician on two customers, sees those two and changes their details,
  // but not the third customer, and has no Admin.
  const bobContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const bobPage = await bobContext.newPage();
  await signIn(bobPage, "e2e-bob");
  await setUpAuthenticatorApp(bobPage);
  await call(bobPage, "PATCH", "/account", { theme: "system" });
  await bobPage.goto(`/customers/${fjordlys.id}`);
  await expect(menu(bobPage).getByRole("link", { name: "Customer settings" })).toBeVisible();
  await expect(menu(bobPage).getByRole("link", { name: "Admin", exact: true })).toHaveCount(0);
  await shotsOf(bobPage, "light")("6-technician");
  await menu(bobPage).getByRole("button", { name: /^Customer/ }).click();
  const picker = bobPage.getByRole("dialog", { name: "Choose a customer" });
  await expect(picker.getByRole("button")).toHaveCount(2);
  await expect(picker).not.toContainText("Sølvbjerg");
  expect((await bobPage.request.get(`/api/customers/${solvbjerg.id}`)).status()).toBe(404);

  // Aud, the auditor, sees every customer as an overview only: no details, no
  // contacts, and no customer sections in the menu.
  const audContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const audPage = await audContext.newPage();
  await signIn(audPage, "e2e-auditor");
  await setUpAuthenticatorApp(audPage);
  await call(audPage, "PATCH", "/account", { theme: "system" });
  await audPage.goto("/customers");
  await expect(audPage.getByRole("row").filter({ hasText: "Overview only" })).toHaveCount(3);
  await audPage.goto(`/customers/${fjordlys.id}`);
  await expect(audPage.getByRole("heading", { name: "Overview only" })).toBeVisible();
  await expect(audPage.getByText("Sigrid Holm")).toHaveCount(0);
  await expect(menu(audPage).getByRole("link", { name: "Contacts & sites" })).toHaveCount(0);
  await shotsOf(audPage, "light")("7-auditor");

  // Not assertions: every page, in both themes, on a desktop and a phone, written
  // to e2e-results/screens for a person to look over.
  const tour = async (page: Page, who: string, stops: [string, string][]) => {
    for (const [size, viewport] of [
      ["desktop", { width: 1440, height: 900 }],
      ["phone", { width: 390, height: 844 }],
    ] as const) {
      await page.setViewportSize(viewport);
      for (const theme of ["light", "dark"] as const) {
        await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
        for (const [name, path] of stops) {
          await page.goto(path);
          await page.getByRole("heading", { level: 1 }).first().waitFor();
          await page.waitForLoadState("networkidle");
          await page.screenshot({
            path: `e2e-results/screens/page-${who}-${name}-${theme}-${size}.png`,
            fullPage: true,
          });
        }
      }
    }
  };
  const customer = `/customers/${fjordlys.id}`;
  await tour(mette, "admin", [
    ["01-home", "/"],
    ["02-customers", "/customers"],
    ["03-customer-new", "/customers/new"],
    ["04-overview", customer],
    ["05-contacts", `${customer}/contacts`],
    ["06-people", `${customer}/people`],
    ["07-settings", `${customer}/settings`],
    ["08-empty-customer", `/customers/${solvbjerg.id}`],
    ["09-account", "/account"],
    ["10-users", "/admin/users"],
  ]);
  await tour(bobPage, "technician", [
    ["01-home", "/"],
    ["02-customers", "/customers"],
    ["03-overview", customer],
    ["04-people", `${customer}/people`],
    ["05-settings", `${customer}/settings`],
  ]);
  await tour(audPage, "auditor", [
    ["01-home", "/"],
    ["02-customers", "/customers"],
    ["03-customer", customer],
  ]);

  expect(violations).toEqual([]);
  await metteContext.close();
  await bobContext.close();
  await audContext.close();
});
