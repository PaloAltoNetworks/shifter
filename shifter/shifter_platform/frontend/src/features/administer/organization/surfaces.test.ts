import { describe, expect, it } from "vitest";

import type { PrincipalWorkspaceContext } from "@/api/types";

import { resolveSelectedWorkspace, surfaceEnabled, WORKSPACE_SURFACES } from "./surfaces";

function ctx(overrides: Partial<PrincipalWorkspaceContext> = {}): PrincipalWorkspaceContext {
  return {
    organization: { uuid: "org-1", name: "Acme" },
    workspace_uuid: "ws-1",
    workspace_name: "Blue",
    is_personal: false,
    role: "member",
    capabilities: ["read_self_membership"],
    ...overrides,
  };
}

describe("resolveSelectedWorkspace", () => {
  it("returns null when the caller has no workspaces", () => {
    expect(resolveSelectedWorkspace([], "ws-1")).toBeNull();
    expect(resolveSelectedWorkspace([], undefined)).toBeNull();
  });

  it("falls back to the first workspace when no UUID is supplied", () => {
    const first = ctx({ workspace_uuid: "ws-1" });
    const second = ctx({ workspace_uuid: "ws-2" });
    expect(resolveSelectedWorkspace([first, second], undefined)).toBe(first);
  });

  it("returns the exact UUID match", () => {
    const first = ctx({ workspace_uuid: "ws-1" });
    const second = ctx({ workspace_uuid: "ws-2" });
    expect(resolveSelectedWorkspace([first, second], "ws-2")).toBe(second);
  });

  it("returns null for an invalid/stale UUID and never silently picks another workspace", () => {
    const personal = ctx({ workspace_uuid: "ws-personal", is_personal: true });
    const shared = ctx({ workspace_uuid: "ws-shared" });
    // A stale/unknown UUID must not resolve to the personal workspace or any other.
    expect(resolveSelectedWorkspace([personal, shared], "ws-unknown")).toBeNull();
  });
});

describe("surfaceEnabled", () => {
  const membership = WORKSPACE_SURFACES.find((s) => s.key === "membership")!;
  const invitations = WORKSPACE_SURFACES.find((s) => s.key === "invitations")!;

  it("enables an ungated surface regardless of capabilities", () => {
    const users = WORKSPACE_SURFACES.find((s) => s.key === "users")!;
    expect(surfaceEnabled(users, ctx({ capabilities: [] }))).toBe(true);
  });

  it("gates a capability-bound surface on any advertised operation", () => {
    // Roster access (owner/admin) enables it.
    expect(surfaceEnabled(membership, ctx({ capabilities: ["read_members"] }))).toBe(true);
    // Self-service leave (every member) also enables it — a member lacks read_members.
    expect(surfaceEnabled(membership, ctx({ capabilities: ["read_self_membership", "leave_workspace"] }))).toBe(true);
    // Neither the roster nor the self-service capability → disabled.
    expect(surfaceEnabled(membership, ctx({ capabilities: ["read_self_membership"] }))).toBe(false);
    expect(surfaceEnabled(membership, null)).toBe(false);
    expect(surfaceEnabled(invitations, ctx({ capabilities: ["read_invitations"] }))).toBe(true);
    expect(surfaceEnabled(invitations, ctx({ capabilities: ["read_members"] }))).toBe(false);
  });

  it("gates range scoping on the owner/admin scope-admin capability", () => {
    const rangeScoping = WORKSPACE_SURFACES.find((s) => s.key === "range-scoping")!;
    expect(surfaceEnabled(rangeScoping, ctx({ capabilities: ["list_range_scope_bindings"] }))).toBe(true);
    expect(surfaceEnabled(rangeScoping, ctx({ capabilities: ["read_members"] }))).toBe(false);
    expect(surfaceEnabled(rangeScoping, null)).toBe(false);
  });
});
