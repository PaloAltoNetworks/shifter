import { defineConfig, devices } from "@playwright/test";

// PR-lane base-URL policy (ADR-055-R7 / #1526 preflight): the authenticated
// hermetic lane targets a loopback http origin only, and the target must match
// the server this config spawns. A credentialed, fragmented, non-loopback,
// non-http, or otherwise inconsistent target is refused at config load. A future
// deployed/on-demand mode (a closed allowlisted environment) rides with the
// deployed tier (#2117), not this lane.
function resolvePrTarget(): { origin: string; host: string; port: string } {
  const raw = process.env.SPA_E2E_BASE_URL ?? "http://127.0.0.1:8000";
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    // Never echo the raw value: it may carry credentials.
    throw new Error("SPA_E2E_BASE_URL is not a valid URL.");
  }
  const loopbackHosts = new Set(["127.0.0.1", "localhost"]);
  if (url.protocol !== "http:" || !loopbackHosts.has(url.hostname) || url.username || url.password || url.hash) {
    throw new Error("SPA_E2E_BASE_URL must be a credential-free http loopback (127.0.0.1/localhost) URL.");
  }
  return { origin: url.origin, host: url.hostname, port: url.port || "8000" };
}

const target = resolvePrTarget();

export default defineConfig({
  testDir: "./e2e",
  // The journeys share one job-local database; serialize deliberately so
  // concurrent mutation journeys never race on the same actor/records.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  // Remove the captured authenticated storageState after the suite, including
  // failure paths (the sessions are synthetic but must not linger on disk).
  globalTeardown: "./e2e/global-teardown.ts",
  use: {
    baseURL: target.origin,
    // Authenticated traces are retained only on a local retry and are never
    // uploaded as CI artifacts (ADR-055-R7). Debug by local reproduction.
    trace: "on-first-retry",
  },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      dependencies: ["setup"],
      testIgnore: /auth\.setup\.ts/,
    },
  ],
  webServer: {
    // The CI job builds the SPA, migrates, and seeds before Playwright runs;
    // this starts the ASGI server (daphne) bound to the same origin as baseURL.
    // Never reuse an existing server: a stray process would not use the
    // database this lane prepared, so a port clash must fail loudly instead.
    command: `uv run python manage.py runserver ${target.host}:${target.port} --noreload`,
    cwd: "..",
    url: `${target.origin}/dev-login/`,
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
