// Remove the captured authenticated storageState after the suite (including
// failure paths). The session cookies are synthetic and job-local, but must not
// linger on disk beyond the run (ADR-055-R7).

import { rmSync } from "node:fs";

import { AUTH_DIR } from "./support/actors";

export default function globalTeardown(): void {
  rmSync(AUTH_DIR, { recursive: true, force: true });
}
