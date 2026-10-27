import { createHmac } from "node:crypto";
import { expect, type Page } from "@playwright/test";

export const PASSWORD = process.env.E2E_PASSWORD ?? "";

function base32(secret: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of secret.replace(/[\s=]/g, "").toUpperCase()) {
    bits += alphabet.indexOf(char).toString(2).padStart(5, "0");
  }
  const bytes = bits.match(/.{8}/g) ?? [];
  return Buffer.from(bytes.map((byte) => parseInt(byte, 2)));
}

/** The authenticator app's code (RFC 6238), `steps` periods from now. */
export function totp(secret: string, steps = 0): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000) + steps));
  const mac = createHmac("sha1", base32(secret)).update(counter).digest();
  const offset = mac[mac.length - 1] & 0xf;
  return ((mac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).toString().padStart(6, "0");
}

/** Chrome's built-in virtual authenticator: a real WebAuthn device the browser emulates. */
export async function addVirtualPasskey(page: Page): Promise<void> {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2",
      transport: "internal",
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  });
}

/** Fails the test on any Content Security Policy violation the page reports. */
export function watchForCspViolations(page: Page): string[] {
  const violations: string[] = [];
  page.on("console", (message) => {
    if (message.text().includes("Content Security Policy")) violations.push(message.text());
  });
  return violations;
}

export async function signIn(page: Page, username: string, password = PASSWORD): Promise<void> {
  await page.goto("/sign-in");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

export async function saveRecoveryCodes(page: Page): Promise<string[]> {
  // Ten one-time codes, or the break-glass Administrator's one reusable code.
  await expect(page.getByRole("heading", { name: /^Save your recovery codes?$/ })).toBeVisible();
  const codes = await page.locator("ol.codes li").allTextContents();
  const next = page.getByRole("button", { name: "Continue" });
  await expect(next).toBeDisabled();
  await page.getByLabel(/I have saved th(ese codes|is code) somewhere safe/).check();
  await next.click();
  return codes;
}

/** From the set-up page: add an authenticator app, save the codes. Returns the app's secret. */
export async function setUpAuthenticatorApp(page: Page): Promise<string> {
  await page.getByRole("button", { name: /Authenticator app/ }).click();
  const secret = (await page.locator(".secret").textContent()) ?? "";
  await page.getByLabel("6-digit code").fill(totp(secret));
  await page.getByRole("button", { name: "Confirm" }).click();
  await saveRecoveryCodes(page);
  return secret;
}

export async function signOut(page: Page): Promise<void> {
  // At phone width the side menu, with the button, opens first.
  const opener = page.getByRole("button", { name: "Open the menu" });
  if (await opener.isVisible()) await opener.click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/sign-in$/);
}

/** A toast on screen with this text (screen readers get a hidden copy too). */
export function toastWith(page: Page, text: string | RegExp) {
  return page
    .getByRole("region", { name: "Notifications" })
    .getByRole("listitem")
    .filter({ hasText: text });
}

/** Dismiss every toast on screen, so the next one shows at once (three at most show).
 * One at a time: a dismissed toast fades out before it leaves. */
export async function dismissToasts(page: Page): Promise<void> {
  const dismiss = page.getByRole("region", { name: "Notifications" }).getByRole("button", { name: "Dismiss" });
  while ((await dismiss.count()) > 0) {
    const button = await dismiss.first().elementHandle();
    if (!button) continue;
    await button.click();
    await button.waitForElementState("hidden");
  }
}
