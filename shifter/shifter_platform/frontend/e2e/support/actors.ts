// Synthetic E2E actors. Staff / threat-research / standard are pre-seeded by the
// `seed_e2e` management command (dev_login cannot set is_staff or the Threat
// Research group); the CTF organizer/participant sessions are established by
// dev_login itself. Each actor's authenticated session is captured once by
// auth.setup.ts into a storageState file the journey specs reuse.

export type DevUserType = "standard" | "ctf_organizer" | "ctf_participant";

export interface Actor {
  readonly email: string;
  readonly userType: DevUserType;
  /** storageState path, relative to the Playwright config (frontend/). */
  readonly state: string;
}

/** Directory holding per-actor storageState; created 0700 and removed after the run. */
export const AUTH_DIR = "playwright/.auth";

export const ACTORS = {
  staff: { email: "e2e-staff@example.com", userType: "standard", state: `${AUTH_DIR}/staff.json` },
  threat: { email: "e2e-threat@example.com", userType: "standard", state: `${AUTH_DIR}/threat.json` },
  standard: { email: "e2e-standard@example.com", userType: "standard", state: `${AUTH_DIR}/standard.json` },
  organizer: { email: "e2e-organizer@example.com", userType: "ctf_organizer", state: `${AUTH_DIR}/organizer.json` },
  participant: { email: "e2e-participant@example.com", userType: "ctf_participant", state: `${AUTH_DIR}/participant.json` },
} as const satisfies Record<string, Actor>;

export type ActorName = keyof typeof ACTORS;
