import { expect, test } from "@playwright/test";
import {
  dismissToasts,
  setUpAuthenticatorApp,
  signIn,
  toastWith,
  totp,
  watchForCspViolations,
} from "./helpers";

// Email and the certificate. There's no mail server here, so the test message fails,
// plainly; the certificate stays Caddy's own, which the browser tests trust.
test("email and the certificate: saved after confirming, and refused plainly", async ({ page }) => {
  const violations = watchForCspViolations(page);
  await signIn(page, "e2e-postmaster");
  const secret = await setUpAuthenticatorApp(page);
  const menu = page.getByRole("navigation", { name: "Main" });

  await menu.getByRole("link", { name: "Admin", exact: true }).click();
  await menu.getByRole("link", { name: "Email", exact: true }).click();
  await expect(page.getByRole("heading", { name: "How mail goes out" })).toBeVisible();
  await page.getByLabel("Mail server").fill("smtp.nordlys.invalid");
  await page.getByLabel("Connection security").selectOption("tls");
  await expect(page.getByLabel("Port")).toHaveValue("465");
  await page.getByLabel("User name (optional)").fill("ting");
  await page.getByLabel("Password").fill("mail password from the e2e test");
  await page.getByLabel("Mail comes from").fill("ting@nordlys.invalid");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const stepUp = page.getByRole("dialog", { name: "Confirm it's you" });
  await stepUp.getByLabel("Code from your authenticator app").fill(totp(secret, 1));
  await stepUp.getByRole("button", { name: "Verify code" }).click();
  await expect(toastWith(page, "Email settings saved.")).toBeVisible();
  await expect(page.getByLabel("Password")).toHaveValue("");
  await expect(page.getByLabel("Password")).toHaveAttribute("placeholder", "Saved; type to replace it");

  await page.getByLabel("Send it to").fill("ingrid@nordlys.invalid");
  await page.getByRole("button", { name: "Send test message" }).click();
  await expect(toastWith(page, "Þing can't find a mail server called smtp.nordlys.invalid")).toBeVisible();
  await page.screenshot({ path: "e2e-results/screens/server-1-email.png", fullPage: true });
  await dismissToasts(page);

  await menu.getByRole("link", { name: "Certificate", exact: true }).click();
  const served = page.getByRole("region", { name: "Serving now" });
  await expect(served).toContainText("Þing's own certificate authority");
  await expect(served).toContainText("localhost, from Caddy Local Authority");
  // Caddy's own certificates last hours and are renewed on their own.
  await expect(served).toContainText(/\(expires in \d+ hours?\)\. Caddy renews it on its own/);
  const root = await page.request.get("/ting-root.crt");
  expect(root.headers()["content-type"]).toBe("application/x-x509-ca-cert");
  expect(await root.text()).toContain("-----BEGIN CERTIFICATE-----");

  await page.getByRole("radio", { name: /Your organisation's certificate/ }).check();
  const notPem = { name: "ting.pem", mimeType: "application/x-pem-file", buffer: Buffer.from("hello") };
  await page.getByLabel("Certificate", { exact: true }).setInputFiles(notPem);
  await page.getByLabel("Private key").setInputFiles({ ...notPem, name: "ting.key" });
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(toastWith(page, "That isn't a certificate in PEM form")).toBeVisible();
  await dismissToasts(page);

  await page.getByRole("radio", { name: /Let's Encrypt/ }).check();
  await expect(page.getByText("must be reachable from the internet")).toBeVisible();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(toastWith(page, "and localhost isn't one")).toBeVisible();
  await dismissToasts(page);

  // Through DNS, for a server the internet can't reach: still only for a public name.
  await page.getByRole("radio", { name: /Through your DNS/ }).check();
  await expect(page.getByText("must be in public DNS")).toBeVisible();
  await page.getByLabel("Your DNS is at").selectOption("rfc2136");
  await page.getByLabel("DNS server").fill("ns1.nordlys.invalid");
  await page.getByLabel("TSIG key name").fill("ting-acme.");
  await page.getByLabel("TSIG key", { exact: true }).fill("cWnu6Ju9zOki4f7Q+da2KKGo0KOXbCf6Pej6hW3geC4=");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(toastWith(page, "and localhost isn't one")).toBeVisible();
  await page.screenshot({ path: "e2e-results/screens/server-2-certificate.png", fullPage: true });

  expect(violations).toEqual([]);
});
