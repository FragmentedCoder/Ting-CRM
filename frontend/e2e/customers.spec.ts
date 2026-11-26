import { expect, test, type Browser, type Locator, type Page } from "@playwright/test";
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

/** A page under one of the customer's fold-out groups in the side menu. */
async function openUnder(page: Page, groupName: string, name: string) {
  const group = page.getByRole("navigation", { name: "Main" }).getByRole("button", { name: groupName });
  if ((await group.getAttribute("aria-expanded")) !== "true") await group.click();
  await menu(page, name).click();
}

const openContacts = (page: Page) => openUnder(page, "Contacts and systems", "Contacts and sites");

/** Where something is on the page: its edges, in pixels. */
async function edges(part: Locator) {
  const box = await part.boundingBox();
  if (!box) throw new Error("Not on the page.");
  return { left: box.x, right: box.x + box.width, top: box.y, bottom: box.y + box.height, width: box.width };
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
  /** A day some days from today, as a date field takes it. */
  const day = (offset: number) => new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);

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
  // Its header says who it is in a line (the address on one line), with its status
  // across from the name: on the name's line, at the header's right edge.
  await expect(boss.getByRole("main")).toContainText("Havnegade 4, 8000 Aarhus C");
  const header = boss.getByRole("main").locator("header");
  const name = await edges(header.getByRole("heading", { name: CUSTOMER }));
  const status = await edges(header.getByText("Active customer"));
  expect(status.left).toBeGreaterThan(name.right);
  expect(Math.abs(status.right - (await edges(header)).right)).toBeLessThan(2);
  expect((status.top + status.bottom) / 2).toBeGreaterThan(name.top);
  expect((status.top + status.bottom) / 2).toBeLessThan(name.bottom);
  await expect(boss.getByRole("button", { name: `Customer ${CUSTOMER}` })).toBeVisible();
  await expect(menu(boss, "Overview")).toHaveAttribute("aria-current", "page");

  // Its sites and contacts, then who works with it.
  await openContacts(boss);
  await boss.getByRole("button", { name: "Add a site" }).click();
  // Every form with many fields is wide, its fields side by side.
  const place = boss.getByRole("dialog");
  expect((await edges(place)).width).toBeGreaterThan(800);
  expect((await edges(place.getByLabel("Type"))).top).toBe((await edges(place.getByLabel("Name"))).top);
  await shot(boss, "1a-site-form");
  await boss.getByRole("dialog").getByLabel("Name").fill("Hovedkontor");
  await boss.getByRole("dialog").getByLabel("Address").fill("Havnegade 4");
  await boss.getByRole("button", { name: "Save site" }).click();
  await boss.getByRole("button", { name: "Add a contact" }).click();
  const contact = boss.getByRole("dialog");
  await contact.getByLabel("Name").fill("Sigrid Holm");
  await contact.getByLabel("Title").fill("IT manager");
  await contact.getByRole("checkbox", { name: "Technical contact" }).check();
  await contact.getByLabel("Email").fill("sigrid@fjordlys.example");
  expect((await edges(contact)).width).toBeGreaterThan(800);
  expect((await edges(contact.getByLabel("Title"))).top).toBe((await edges(contact.getByLabel("Name"))).top);
  await shot(boss, "1a-contact-form");
  await contact.getByRole("button", { name: "Save contact" }).click();
  // Every site has its own contact: Sigrid becomes Hovedkontor's.
  await boss.getByRole("button", { name: "Change site" }).click();
  await boss.getByRole("dialog").getByLabel("Contact at this site").selectOption({ label: "Sigrid Holm" });
  await boss.getByRole("button", { name: "Save site" }).click();
  const hovedkontor = boss.getByRole("listitem").filter({ hasText: "Hovedkontor" });
  await expect(hovedkontor).toContainText("Contact at this site");
  await expect(hovedkontor).toContainText("Technical contact");
  const card = boss.getByRole("region", { name: "For the whole company" }).getByRole("listitem").filter({ hasText: "Sigrid Holm" });
  await expect(card.getByText("sigrid@fjordlys.example")).toBeVisible();
  // The card's menu is in its top right corner.
  const corner = await edges(card);
  const more = await edges(card.getByRole("button", { name: "Actions for Sigrid Holm" }));
  expect(corner.right - more.right).toBeLessThan(12);
  expect(more.top - corner.top).toBeLessThan(12);
  await shot(boss, "1-contacts");

  await menu(boss, "People").click();
  // Only technicians can be assigned: the auditor and the manager aren't offered.
  await expect(boss.getByRole("checkbox", { name: /Aud Auditor/ })).toHaveCount(0);
  await expect(boss.getByRole("checkbox", { name: /Maja Manager/ })).toHaveCount(0);
  // A tile per technician, saying what else they have; nothing to save until one changes.
  const save = boss.getByRole("button", { name: "Save", exact: true });
  await expect(save).toBeDisabled();
  await expect(boss.getByRole("checkbox", { name: /Tor Tekniker/ })).toHaveAccessibleName(/No other customers/);
  await boss.getByRole("checkbox", { name: /Tor Tekniker/ }).check();
  await expect(boss.getByRole("main")).toContainText(/1 of \d+ technicians/);
  await boss.getByRole("button", { name: "Undo changes" }).click();
  await expect(boss.getByRole("checkbox", { name: /Tor Tekniker/ })).not.toBeChecked();
  await boss.getByRole("checkbox", { name: /Tor Tekniker/ }).check();
  await shot(boss, "1b-people");
  await save.click();
  await expect(toastWith(boss, "Who works with this customer is saved.")).toBeVisible();
  await menu(boss, "Overview").click();
  await expect(boss.getByRole("region", { name: "People on this customer" })).toContainText("Tor Tekniker");
  await shot(boss, "2-overview");

  // A pinned warning: one line every technician sees first.
  await boss.getByRole("button", { name: "Pin a warning" }).click();
  await boss.getByRole("dialog").getByLabel("Warning").fill("Do not update in working hours");
  await boss.getByRole("dialog").getByRole("radio", { name: "A hard rule (red)" }).check();
  await boss.getByRole("button", { name: "Pin warning" }).click();
  const pinned = boss.getByRole("note", { name: "Pinned warnings" });
  await expect(pinned).toContainText("Do not update in working hours");
  await expect(pinned).toContainText("1 of 3");

  // Its support, copied from the standard Support service, with the case number
  // time goes on; the overview shows both in its first tiles.
  // The catalog's form is wide too: a detail worth recording takes one line.
  await menu(boss, "Standard services").click();
  await boss.getByRole("button", { name: "Add a service" }).click();
  const standard = boss.getByRole("dialog");
  await standard.getByRole("button", { name: "Add a detail" }).click();
  await standard.getByLabel("Kind").selectOption({ label: "A choice" });
  expect((await edges(standard)).width).toBeGreaterThan(800);
  expect((await edges(standard.getByLabel("Description"))).top).toBe((await edges(standard.getByLabel("Name"))).top);
  expect((await edges(standard.getByLabel("Help", { exact: true }))).top).toBe((await edges(standard.getByLabel("Detail", { exact: true }))).top);
  await shot(boss, "2-standard-service-form");
  await standard.getByRole("button", { name: "Cancel" }).click();

  await openUnder(boss, "Services and agreements", "Services");
  await boss.getByRole("button", { name: "Add a service" }).click();
  const service = boss.getByRole("dialog");
  await service.getByLabel("Standard service").selectOption({ label: "Support" });
  await service.getByLabel("When it applies").selectOption({ label: "Working hours" });
  await service.getByLabel("Log time on (case number)").fill("TDSE26114");
  await service.getByLabel("Kind of case").selectOption({ label: "Monthly" });
  expect((await edges(service)).width).toBeGreaterThan(800);
  expect((await edges(service.getByLabel("Status"))).top).toBe((await edges(service.getByLabel("Standard service"))).top);
  await shot(boss, "2-service-form");
  await service.getByRole("button", { name: "Save service" }).click();
  await expect(boss.getByRole("heading", { name: "Support", exact: true })).toBeVisible();
  await menu(boss, "Overview").click();
  const glance = boss.getByLabel("At a glance");
  await expect(glance).toContainText("Working hours");
  await expect(glance).toContainText("TDSE26114");

  // An agreement whose section covers it: until then Support had no agreement.
  await expect(boss.getByRole("main")).toContainText("Support: no agreement");
  await openUnder(boss, "Services and agreements", "Agreements");
  await boss.getByRole("button", { name: "New agreement" }).click();
  const agreement = boss.getByRole("dialog");
  await agreement.getByLabel("Name", { exact: true }).fill("Service agreement 2026");
  await agreement.getByLabel("Starts on").fill(day(-10));
  await agreement.getByRole("button", { name: "Add a section" }).click();
  await agreement.getByLabel("Section", { exact: true }).fill("§ 3.1");
  await agreement.getByLabel("Covers").selectOption({ label: "Support" });
  // The form is wide, its fields side by side: the name, kind and status share a line.
  expect((await edges(agreement)).width).toBeGreaterThan(800);
  expect((await edges(agreement.getByLabel("Status"))).top).toBe((await edges(agreement.getByLabel("Name", { exact: true }))).top);
  await agreement.getByRole("button", { name: "Add a version" }).click();
  await shot(boss, "2a-agreement-form");
  await agreement.getByRole("button", { name: "Remove version 1" }).click();
  await agreement.getByRole("button", { name: "Save agreement" }).click();
  await expect(boss.getByRole("heading", { name: "Service agreement 2026" })).toBeVisible();
  await expect(boss.getByRole("main")).toContainText("Covers 1 of 1 services");
  await shot(boss, "2b-agreement");

  // The technician starts on My work, opens the customer and keeps its details and
  // contacts up to date, but doesn't choose how long its records are kept, its logo
  // or who works with it, and can't delete it.
  const { context: techContext, page: tech } = await signedIn(browser, "e2e-tech", { clock: true });
  await expect(tech.getByRole("heading", { name: "My tasks" })).toBeVisible();
  // The phone rings: Ctrl+K finds the customer by who's calling, and a few letters of
  // its name and Enter open it.
  await tech.keyboard.press("Control+k");
  const search = tech.getByRole("combobox", { name: /^Search customers/ });
  await search.fill("sigrid");
  await expect(tech.getByRole("option", { name: /Sigrid Holm/ })).toContainText(CUSTOMER);
  await search.fill("fjordlys");
  await expect(tech.getByRole("option").first()).toContainText("Customer");
  await shot(tech, "3a-search");
  await search.press("Enter");
  await expect(tech.getByRole("heading", { name: CUSTOMER })).toBeVisible();
  await expect(tech.getByRole("note", { name: "Pinned warnings" })).toContainText("Do not update in working hours");
  await expect(tech.getByRole("button", { name: "Pin a warning" })).toHaveCount(0);
  await menu(tech, "Customer settings").click();
  await tech.getByLabel("Address").fill("Havnegade 6\n8000 Aarhus C");
  await tech.getByRole("button", { name: "Save details" }).click();
  await expect(toastWith(tech, "Details saved.")).toBeVisible();
  await expect(tech.getByLabel("Keep its records for")).toHaveCount(0);
  await expect(tech.getByRole("heading", { name: "Logo" })).toHaveCount(0);
  await expect(tech.getByRole("button", { name: "Delete customer" })).toHaveCount(0);
  await shot(tech, "3-technician-settings");
  await openContacts(tech);
  await tech.getByRole("button", { name: "Add a contact" }).click();
  await tech.getByRole("dialog").getByLabel("Name").fill("Anders Vang");
  await tech.getByRole("dialog").getByRole("button", { name: "Save contact" }).click();
  await expect(tech.getByText("Anders Vang")).toBeVisible();

  // The technician records the customer's systems: a host, and a virtual machine on it.
  await menu(tech, "Systems").click();
  await tech.getByRole("button", { name: "Add a system" }).click();
  const system = tech.getByRole("dialog");
  await system.getByLabel("Name", { exact: true }).fill("HV01");
  await system.getByLabel("Role").fill("Hyper-V host");
  // The form is wide, four fields to a line, so it isn't a long scroll.
  expect((await edges(system)).width).toBeGreaterThan(800);
  expect((await edges(system.getByLabel("Type"))).top).toBe((await edges(system.getByLabel("Name", { exact: true }))).top);
  await shot(tech, "3-system-form");
  await system.getByRole("button", { name: "Save system" }).click();
  await tech.getByRole("button", { name: "Add a system" }).click();
  await system.getByLabel("Name", { exact: true }).fill("DC01");
  await system.getByLabel("Type").selectOption({ label: "Virtual machine" });
  await system.getByLabel("Runs on").selectOption({ label: "HV01" });
  await system.getByRole("button", { name: "Save system" }).click();
  const list = tech.getByRole("navigation", { name: `${CUSTOMER}'s systems` });
  await expect(list.getByRole("link", { name: /DC01/ })).toContainText("VM");
  await list.getByRole("link", { name: /HV01/ }).click();
  await expect(tech.getByRole("region", { name: "Runs on this host" })).toContainText("DC01");

  // Agreements are the Managers': the technician reads them.
  await openUnder(tech, "Services and agreements", "Agreements");
  await expect(tech.getByText("Read-only: agreements are changed by a Manager.")).toBeVisible();
  await expect(tech.getByRole("button", { name: "Change agreement" })).toHaveCount(0);

  // The technician logs work: a line from the overview, then with its service, which
  // fills in the case number and says the work is covered.
  await menu(tech, "Overview").click();
  await tech.getByRole("textbox", { name: "Log work" }).fill("Replaced the switch in the server room");
  await tech.getByRole("button", { name: "Log work", exact: true }).click();
  await expect(tech.getByRole("region", { name: "Latest work" })).toContainText("Replaced the switch in the server room");
  await tech.getByRole("button", { name: "More…" }).click();
  const work = tech.getByRole("dialog");
  await work.getByLabel("What was done").fill("Reset a password for Sigrid");
  await work.getByLabel("Type", { exact: true }).selectOption({ label: "Call" });
  await work.getByLabel("Service", { exact: true }).selectOption({ label: "Support" });
  await expect(work.getByLabel("Log time on (case number)")).toHaveValue("TDSE26114");
  await expect(work).toContainText("Covered by Service agreement 2026.");
  // It's the day of the work that counts: done before the agreement began, it's billable.
  const now = await work.getByLabel("When").inputValue();
  await work.getByLabel("When").fill(`${day(-20)}T10:00`);
  await expect(work).toContainText(/No agreement covered it on .+: the work is billable\./);
  await work.getByLabel("When").fill(now);
  await expect(work).toContainText("Covered by Service agreement 2026.");
  // Work that hasn't happened yet can't be logged: tomorrow is out of range.
  await work.getByLabel("When").fill(`${day(1)}T10:00`);
  expect(await work.getByLabel("When").evaluate((field: HTMLInputElement) => field.validity.rangeOverflow)).toBe(true);
  await work.getByLabel("When").fill(now);
  await work.getByRole("button", { name: "Log work" }).click();
  await openUnder(tech, "Timeline and work log", "Work log");
  const entries = tech.getByRole("region", { name: "Entries" });
  await expect(entries).toContainText("Reset a password for Sigrid");
  await expect(entries).toContainText("Covered");
  await expect(entries).toContainText("TDSE26114");
  await shot(tech, "3b-work-log");

  // The timeline: an overdue recurring task is ticked off into the work log and comes
  // back; a renewal is recorded, and waits for a Manager's decision.
  await openUnder(tech, "Timeline and work log", "Timeline");
  const line = tech.getByRole("group", { name: "The line, the latest first" });
  await expect(line).toContainText("Today");
  await expect(line).toContainText("Reset a password for Sigrid");
  await tech.getByRole("button", { name: "New task" }).click();
  const task = tech.getByRole("dialog");
  await task.getByLabel("What needs doing").fill("Update the firewall's firmware");
  await task.getByLabel("Due").fill(day(-3));
  await task.getByLabel("It repeats").check();
  await task.getByLabel("Service", { exact: true }).selectOption({ label: "Support" });
  await task.getByRole("button", { name: "Add task" }).click();
  await expect(line).toContainText("Overdue by 3 days");
  await line.getByRole("button", { name: "Mark done" }).click();
  const done = tech.getByRole("dialog");
  await expect(done).toContainText("Every 3 months: the next one will be due");
  await done.getByLabel("What was done").fill("Updated both nodes to 7.4.2");
  await done.getByRole("button", { name: "Mark done" }).click();
  await expect(line).toContainText("Update the firewall's firmware: Updated both nodes to 7.4.2");
  await expect(line).not.toContainText("Overdue");
  await expect(line.getByText("Update the firewall's firmware", { exact: true })).toBeVisible();
  // An older time, filled in afterwards, lands in the work log on its own day and
  // doesn't move the next one back: that still counts from today, the newest.
  const monthOf = (iso: string) =>
    new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
  await tech.getByRole("button", { name: "Actions for “Update the firewall's firmware”" }).click();
  await tech.getByRole("menuitem", { name: "Mark done" }).click();
  await done.getByLabel("Done on").fill(day(-40));
  await expect(done).toContainText("An older time doesn't move it back");
  await done.getByLabel("What was done").fill("Updated to 7.3.9");
  await done.getByRole("button", { name: "Mark done" }).click();
  await expect(line.getByRole("region", { name: monthOf(day(-40)) })).toContainText(
    "Update the firewall's firmware: Updated to 7.3.9");
  await expect(line.getByRole("region", { name: monthOf(day(0)) })).toContainText("Updated both nodes to 7.4.2");
  await expect(line.getByText("Update the firewall's firmware", { exact: true })).toBeVisible();
  await tech.getByRole("button", { name: "New renewal" }).click();
  const renewal = tech.getByRole("dialog");
  await renewal.getByLabel("What renews").fill("Firewall feature key");
  await renewal.getByLabel("Renews on").fill(day(20));
  await renewal.getByRole("button", { name: "Add renewal" }).click();
  await expect(line).toContainText("Renewal open");
  await tech.getByRole("button", { name: "Actions for “Firewall feature key”" }).click();
  await expect(tech.getByRole("menuitem", { name: "Mark as renewed" })).toBeVisible();
  await expect(tech.getByRole("menuitem", { name: "Record the decision" })).toHaveCount(0);
  await tech.keyboard.press("Escape");
  await shot(tech, "3c-timeline");

  // My work gathers it: the task that's his, the renewal coming up, the customer that
  // needs attention because of it, and the customer he just looked at. A task is
  // added and ticked off from there, for a customer he chooses.
  await menu(tech, "My work").click();
  const mine = tech.getByRole("region", { name: "My tasks" });
  await expect(mine).toContainText("Update the firewall's firmware");
  await expect(tech.getByRole("region", { name: "Renewals and notice days" })).toContainText("Firewall feature key");
  await expect(tech.getByRole("region", { name: "Customers needing attention" })).toContainText(
    /Renewal in \d+ days: Firewall feature key/,
  );
  await expect(tech.getByRole("region", { name: "Recently viewed" })).toContainText(CUSTOMER);
  await tech.getByRole("button", { name: "New task" }).click();
  await expect(tech.getByRole("dialog").getByLabel("Customer")).toContainText(CUSTOMER);
  await tech.getByRole("dialog").getByRole("button", { name: "Continue" }).click();
  await tech.getByRole("dialog").getByLabel("What needs doing").fill("Order a spare switch");
  await tech.getByRole("dialog").getByLabel("Due").fill(day(2));
  await tech.getByRole("dialog").getByRole("button", { name: "Add task" }).click();
  await expect(mine).toContainText("Order a spare switch");
  await shot(tech, "3d-my-work");
  await tech.getByRole("button", { name: "Mark “Order a spare switch” as done" }).click();
  await tech.getByRole("dialog").getByRole("button", { name: "Mark done" }).click();
  await expect(mine).not.toContainText("Order a spare switch");
  // All customers has it at a glance: one service, covered, and the renewal nobody has
  // decided on; the chip narrows the list to the customers that need attention.
  await menu(tech, "All customers").click();
  const listed = tech.getByRole("row", { name: /Fjordlys Energi/ });
  await expect(listed).toContainText(/Renewal in \d+ days: Firewall feature key/);
  await expect(listed.getByRole("cell").nth(2)).toHaveText("1");
  await tech.getByRole("group", { name: "Show" }).getByRole("button", { name: /Needs attention/ }).click();
  await expect(listed).toBeVisible();
  await shot(tech, "3e-all-customers");
  // The overview previews the systems: the virtual machine under its host.
  await listed.getByRole("link", { name: CUSTOMER }).click();
  const systems = tech.getByRole("region", { name: "Systems" });
  await expect(systems).toContainText("HV01");
  await expect(systems.getByRole("listitem").filter({ hasText: "DC01" })).toContainText("VM");
  await expect(systems.getByRole("link", { name: "All 2" })).toBeVisible();
  await shot(tech, "3f-overview");
  await menu(tech, "People").click();
  await expect(tech.getByRole("checkbox")).toHaveCount(0);
  await expect(tech.getByRole("main")).toContainText("Tor Tekniker");

  // The manager sees every customer without being assigned, and runs it: its
  // details, how long its records are kept, its logo and who works with it. No
  // deleting, and of the admin panel only how far ahead Þing looks.
  const { context: managerContext, page: manager } = await signedIn(browser, "e2e-manager");
  await expect(manager.getByRole("heading", { name: "For Managers" })).toBeVisible();
  // The renewal nobody has decided on yet puts the customer among those needing attention.
  await manager.getByRole("region", { name: "Customers needing attention" }).getByRole("link", { name: CUSTOMER }).click();
  await menu(manager, "Customer settings").click();
  await expect(manager.getByLabel("Keep its records for")).toBeVisible();
  await expect(manager.getByRole("heading", { name: "Logo" })).toBeVisible();
  await expect(manager.getByRole("button", { name: "Delete customer" })).toHaveCount(0);
  await menu(manager, "People").click();
  await expect(manager.getByRole("checkbox", { name: /Tor Tekniker/ })).toBeChecked();
  await shot(manager, "4-manager-people");
  await menu(manager, "Admin").click();
  await expect(manager.getByRole("heading", { name: "General" })).toBeVisible();
  await expect(manager.getByLabel("Show what's coming up for the next")).toHaveValue("12");
  await expect(manager.getByRole("switch")).toHaveCount(0);
  await expect(menu(manager, "Users")).toHaveCount(0);
  await manager.getByRole("button", { name: "Save settings" }).click();
  await expect(toastWith(manager, "Settings saved.")).toBeVisible();
  await shot(manager, "4a-manager-general");

  // Deciding on a renewal is the Manager's, in the fixed words; the overview shows it.
  await openUnder(manager, "Timeline and work log", "Timeline");
  await manager.getByRole("button", { name: "Actions for “Firewall feature key”" }).click();
  await manager.getByRole("menuitem", { name: "Record the decision" }).click();
  const decision = manager.getByRole("dialog");
  await decision.getByRole("radio", { name: /^Approved/ }).check();
  await decision.getByRole("button", { name: "Save decision" }).click();
  await expect(manager.getByRole("group", { name: "The line, the latest first" })).toContainText("Approved");
  await menu(manager, "Overview").click();
  const coming = manager.getByRole("region", { name: "Coming up" });
  await expect(coming).toContainText("Firewall feature key");
  await expect(coming).toContainText("Approved");
  await shot(manager, "4b-coming-up");
  // Approved, it no longer needs attention; and an agreement covers what we provide.
  await menu(manager, "My work").click();
  await expect(manager.getByRole("region", { name: "Customers needing attention" })).toContainText("Nothing");
  await expect(manager.getByRole("region", { name: "Services without agreement" })).toContainText(
    "An agreement covers every active service.",
  );
  await shot(manager, "4c-my-work-manager");

  // Limited to the customers he's assigned to, and then unassigned, the technician
  // loses the customer at the next check, without signing in again.
  const customerPage = boss.url();
  await boss.goto("/admin/users");
  await boss.getByRole("link", { name: "Tor Tekniker" }).click();
  const limit = boss.getByRole("checkbox", { name: /Only the customers they're assigned to/ });
  await expect(limit).not.toBeChecked();
  await limit.check();
  await boss.getByRole("button", { name: "Save changes" }).click();
  await expect(toastWith(boss, "Saved.")).toBeVisible();
  await boss.goto(customerPage);
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
