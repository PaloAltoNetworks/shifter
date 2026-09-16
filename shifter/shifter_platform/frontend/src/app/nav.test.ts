import { describe, expect, it } from "vitest";

import type { Bootstrap } from "@/api/types";
import { STAFF_BOOTSTRAP } from "@/test/utils";

import { NAV_GROUPS, isNavEntryVisible, permissionAllows, visibleNavGroups, type NavEntry } from "./nav";

function bootstrap(overrides: Partial<Bootstrap> = {}): Bootstrap {
  return {
    ...STAFF_BOOTSTRAP,
    ...overrides,
    principal: { ...STAFF_BOOTSTRAP.principal, ...(overrides.principal ?? {}) },
    permissions: { ...STAFF_BOOTSTRAP.permissions, ...(overrides.permissions ?? {}) },
    modes: { ...STAFF_BOOTSTRAP.modes, ...(overrides.modes ?? {}) },
  };
}

const STAFF_ENTRY: NavEntry = {
  surface: "Users",
  audience: "organizer",
  routeName: "administer:users",
  permissionPolicy: "staff",
  ownerApp: "management",
  purpose: "users",
  mode: "operator",
  group: "Administer",
  routePath: "/administer",
  iconKey: "user-cog",
};

describe("permissionAllows", () => {
  it("maps each policy to the right bootstrap flag", () => {
    const bs = bootstrap({
      permissions: {
        ...STAFF_BOOTSTRAP.permissions,
        can_access_threat_research: false,
        is_ctf_organizer: true,
        is_ctf_participant: false,
      },
    });
    expect(permissionAllows("authenticated", bs)).toBe(true);
    expect(permissionAllows("threat_research", bs)).toBe(false);
    expect(permissionAllows("ctf_organizer", bs)).toBe(true);
    expect(permissionAllows("ctf_participant", bs)).toBe(false);
    expect(permissionAllows("staff", bs)).toBe(true);
  });

  it("admits the ctf_admin surface for an organizer or platform administrator", () => {
    const organizer = bootstrap({
      permissions: { ...STAFF_BOOTSTRAP.permissions, is_ctf_organizer: true, can_administer_ctf: true },
    });
    expect(permissionAllows("ctf_admin", organizer)).toBe(true);

    const superuserOnly = bootstrap({
      principal: { ...STAFF_BOOTSTRAP.principal, is_superuser: true },
      permissions: { ...STAFF_BOOTSTRAP.permissions, is_ctf_organizer: false, can_administer_ctf: true },
    });
    expect(permissionAllows("ctf_admin", superuserOnly)).toBe(true);

    const neither = bootstrap({
      permissions: { ...STAFF_BOOTSTRAP.permissions, is_ctf_organizer: false, can_administer_ctf: false },
    });
    expect(permissionAllows("ctf_admin", neither)).toBe(false);
  });
});

describe("isNavEntryVisible", () => {
  it("hides an entry when its advisory permission is denied", () => {
    const bs = bootstrap({
      principal: { ...STAFF_BOOTSTRAP.principal, is_staff: false },
    });
    expect(isNavEntryVisible(STAFF_ENTRY, bs)).toBe(false);
  });
});

describe("visibleNavGroups", () => {
  it("returns operator groups filtered by advisory permissions", () => {
    const bs = bootstrap({
      permissions: {
        ...STAFF_BOOTSTRAP.permissions,
        can_access_threat_research: false,
        is_ctf_organizer: false,
        is_ctf_participant: false,
      },
    });
    const groups = visibleNavGroups("operator", bs);
    const names = groups.map((g) => g.group);
    expect(names).toContain("Operate");
    expect(names).toContain("Administer");
    // No threat-research access -> Author (Scenarios) is hidden and its group drops.
    expect(names).not.toContain("Author");
    // No participant mode groups leak into operator mode.
    expect(names).not.toContain("Participate");
  });

  it("returns participant groups only for participant mode", () => {
    const bs = bootstrap({
      permissions: {
        ...STAFF_BOOTSTRAP.permissions,
        can_access_threat_research: false,
        is_ctf_organizer: false,
        is_ctf_participant: true,
      },
    });
    const groups = visibleNavGroups("participant", bs);
    expect(groups.map((g) => g.group)).toEqual(["Participate"]);
    expect(groups[0].entries.map((e) => e.surface)).toContain("Challenges");
  });

  it("filters an entry's children by advisory visibility", () => {
    const bs = bootstrap();
    const operate = visibleNavGroups("operator", bs).find((g) => g.group === "Operate");
    const assets = operate?.entries.find((e) => e.surface === "Assets");
    expect(assets?.children?.map((c) => c.surface)).toEqual(["Agents", "NGFW", "Credentials"]);
  });

  it("exposes CTF participant entries as internal SPA routes (#1372)", () => {
    const bs = bootstrap({ permissions: { ...STAFF_BOOTSTRAP.permissions, is_ctf_participant: true } });
    const [participate] = visibleNavGroups("participant", bs);
    const eventHome = participate.entries.find((e) => e.surface === "Event Home");
    expect(eventHome?.external).toBeFalsy();
    expect(eventHome?.routePath).toBe("/ctf/");
    expect(participate.entries.map((entry) => entry.surface)).not.toContain("Terminal");
    expect(participate.entries.every((e) => !e.external)).toBe(true);
  });

  it("shows the Organization console entry for staff (#1938)", () => {
    const administer = visibleNavGroups("operator", bootstrap()).find((g) => g.group === "Administer");
    const org = administer?.entries.find((e) => e.surface === "Organization");
    expect(org?.routePath).toBe("/administer/organization");
    expect(org?.permissionPolicy).toBe("staff");
    expect(org?.external).toBeFalsy();
  });

  it("keeps the Django Admin escape hatch present and external (#1938)", () => {
    const administer = visibleNavGroups("operator", bootstrap()).find((g) => g.group === "Administer");
    const djangoAdmin = administer?.entries.find((e) => e.surface === "Django Admin");
    expect(djangoAdmin?.external).toBe(true);
    expect(djangoAdmin?.routePath).toBe("/admin/");
  });

  it("keeps Platform Settings as a single staff-owned Administer surface", () => {
    const operate = NAV_GROUPS.find((group) => group.group === "Operate");
    const administer = NAV_GROUPS.find((group) => group.group === "Administer");

    expect(operate?.entries.some((entry) => entry.routeName === "mission_control:settings")).toBe(false);
    const settingsEntries = administer?.entries.filter((entry) => entry.routeName === "administer:settings") ?? [];
    expect(settingsEntries).toHaveLength(1);
    expect(settingsEntries[0]).toMatchObject({ permissionPolicy: "staff", routePath: "/administer/settings" });
    expect(settingsEntries[0].external).toBeFalsy();
  });
});
