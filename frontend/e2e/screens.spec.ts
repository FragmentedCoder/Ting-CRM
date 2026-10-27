import { expect, test } from "@playwright/test";
import { signIn, signOut, totp } from "./helpers";

// Not assertions: screenshots of each screen in both themes and at phone width,
// written to e2e-results/screens for a person to look over. Þing starts light
// whatever the device prefers; the "dark" accounts chose dark, which applies once
// their password is in.
for (const colorScheme of ["light", "dark"] as const) {
  for (const [label, viewport] of [
    ["desktop", { width: 1280, height: 800 }],
    ["phone", { width: 390, height: 844 }],
  ] as const) {
    test(`screens: ${colorScheme}, ${label}`, async ({ browser }) => {
      // Reduced motion, so the phone menu is fully open when it's taken.
      const context = await browser.newContext({ colorScheme, viewport, reducedMotion: "reduce" });
      const page = await context.newPage();
      const username = `e2e-screens-${colorScheme}-${label}`;
      const shot = (name: string) =>
        page.screenshot({
          path: `e2e-results/screens/${name}-${colorScheme}-${label}.png`,
          fullPage: true,
        });

      await page.goto("/sign-in");
      await page.getByRole("heading", { name: "Sign in" }).waitFor();
      // Before anyone signs in, the fjord scene is the light one, even on a dark device.
      await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
      await expect(page.locator(".auth-scene .dark")).toHaveCSS("opacity", "0");
      await shot("1-sign-in");

      await signIn(page, "e2e-wrong", "not the right password at all");
      await page.getByRole("alert").waitFor();
      await shot("2-sign-in-error");

      await signIn(page, username);
      await page.getByRole("heading", { name: "Set up multifactor" }).waitFor();
      await page.mouse.move(0, 0);
      await shot("3-set-up");

      await page.getByRole("button", { name: /Authenticator app/ }).click();
      await page.getByRole("img", { name: /QR code/ }).waitFor();
      await shot("4-authenticator-app");

      const secret = (await page.locator(".secret").textContent()) ?? "";
      await page.getByLabel("6-digit code").fill(totp(secret));
      await page.getByRole("button", { name: "Confirm" }).click();
      await page.getByRole("heading", { name: "Save your recovery codes" }).waitFor();
      await shot("5-recovery-codes");

      await page.getByLabel("I have saved these codes somewhere safe").check();
      await page.getByRole("button", { name: "Continue" }).click();
      await page.getByRole("heading", { name: /Welcome/ }).waitFor();
      await shot("6-home");

      if (label === "phone") {
        await page.getByRole("button", { name: "Open the menu" }).click();
        await page.getByRole("button", { name: "Close the menu" }).last().waitFor();
        await shot("6-menu");
        await page.keyboard.press("Escape");
      }
      await signOut(page);
      await signIn(page, username);
      await page.getByRole("heading", { name: "Confirm it's you" }).waitFor();
      await shot("7-verify");
      await context.close();
    });
  }
}
