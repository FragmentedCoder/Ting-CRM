import { defineConfig, devices } from "@playwright/test";

// Runs against a deployed stack (Caddy in front), not a dev server: the session
// cookie is Secure and __Host- prefixed, and passkeys need a real HTTPS origin.
// See e2e/run.sh.
export default defineConfig({
  testDir: "e2e",
  outputDir: "e2e-results",
  workers: 1, // the tests share one server and one database
  reporter: [["list"]],
  use: {
    baseURL: process.env.TING_URL ?? "https://localhost",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    ...devices["Desktop Chrome"],
  },
  projects: [
    // A fresh install sends every page to the setup wizard, so it runs first.
    { name: "setup", testMatch: /setup\.spec\.ts/ },
    { name: "chromium", testIgnore: /setup\.spec\.ts/, dependencies: ["setup"] },
  ],
});
