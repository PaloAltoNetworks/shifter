import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";

import { ApiError } from "@/api/errors";
import type {
  AddWorkspaceMemberRequest,
  ChangeWorkspaceMemberRoleRequest,
  PrincipalWorkspaceContext,
  WorkspaceMembership,
} from "@/api/types";
import { setupUser } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { WorkspaceContextProvider } from "./WorkspaceContext";
import { WorkspaceMembershipPage } from "./WorkspaceMembershipPage";

const mockApi = vi.mocked(apiFetch);

const WS = "11111111-1111-1111-1111-111111111111";

function ctx(overrides: Partial<PrincipalWorkspaceContext> = {}): PrincipalWorkspaceContext {
  return {
    organization: { uuid: "org-1", name: "Acme" },
    workspace_uuid: WS,
    workspace_name: "Blue",
    is_personal: false,
    role: "owner",
    capabilities: ["read_members", "add_member", "change_member_role", "remove_member", "leave_workspace"],
    ...overrides,
  };
}

function membership(overrides: Partial<WorkspaceMembership> = {}): WorkspaceMembership {
  return {
    membership_id: 1,
    workspace_uuid: WS,
    user_id: 1,
    display_name: "Alice Owner",
    role: "owner",
    created_at: "2026-02-01T00:00:00Z",
    ...overrides,
  };
}

type Override = (path: string, method: string, body: unknown) => Promise<unknown> | undefined;

/**
 * Route apiFetch by path/method against a mutable roster so success paths reflect
 * the post-mutation state on the invalidated refetch — the same "behaves like a
 * real backend" pattern the lifecycle tests use. `overrides` lets a test force a
 * bounded server error (e.g. 409 last_owner_required) for one path.
 */
function stubApi({
  roster,
  self,
  overrides,
}: {
  roster: WorkspaceMembership[];
  self?: WorkspaceMembership;
  overrides?: Override;
}) {
  let members = [...roster];
  const selfMembership = self ?? members[0];
  mockApi.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    const method = options?.method ?? "GET";
    const forced = overrides?.(path, method, options?.body);
    if (forced !== undefined) return forced;

    if (path === `/workspaces/${WS}/memberships/` && method === "GET") return Promise.resolve(members);
    if (path === `/workspaces/${WS}/membership/` && method === "GET") return Promise.resolve(selfMembership);
    if (path === `/workspaces/${WS}/memberships/` && method === "POST") {
      const body = options?.body as AddWorkspaceMemberRequest;
      const created = membership({ user_id: 99, display_name: body.email, role: body.role });
      members = [...members, created];
      return Promise.resolve(created);
    }
    if (path === `/workspaces/${WS}/memberships/leave/` && method === "POST") {
      return Promise.resolve(selfMembership);
    }
    const roleMatch = /^\/workspaces\/[^/]+\/memberships\/(\d+)\/role\/$/.exec(path);
    if (roleMatch && method === "POST") {
      const userId = Number(roleMatch[1]);
      const body = options?.body as ChangeWorkspaceMemberRoleRequest;
      members = members.map((m) => (m.user_id === userId ? membership({ ...m, role: body.role }) : m));
      return Promise.resolve(members.find((m) => m.user_id === userId));
    }
    const removeMatch = /^\/workspaces\/[^/]+\/memberships\/(\d+)\/remove\/$/.exec(path);
    if (removeMatch && method === "POST") {
      const userId = Number(removeMatch[1]);
      const removed = members.find((m) => m.user_id === userId);
      members = members.filter((m) => m.user_id !== userId);
      return Promise.resolve(removed);
    }
    return Promise.reject(new ApiError(404, { code: "not_found", message: "nope" }));
  });
}

function renderMembership(selected: PrincipalWorkspaceContext | null) {
  const router = createMemoryRouter(
    [
      {
        path: "/administer/organization/workspaces/:workspaceUuid/membership",
        element: (
          <WorkspaceContextProvider workspaces={selected ? [selected] : []} selected={selected}>
            <WorkspaceMembershipPage />
          </WorkspaceContextProvider>
        ),
      },
    ],
    { initialEntries: [`/administer/organization/workspaces/${WS}/membership`] },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

// Two owners so remove/demote are enabled and the last-owner note is absent; the
// caller (self) is the second owner, and a plain member rounds out the roster.
function twoOwnerRoster(): WorkspaceMembership[] {
  return [
    membership({ user_id: 1, display_name: "Alice Owner", role: "owner" }),
    membership({ user_id: 2, display_name: "Bob Owner", role: "owner" }),
    membership({ user_id: 3, display_name: "Carol Member", role: "member" }),
  ];
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("WorkspaceMembershipPage — roster (owner/admin)", () => {
  it("renders the roster with each member and their role", async () => {
    stubApi({ roster: twoOwnerRoster(), self: membership({ user_id: 2, display_name: "Bob Owner", role: "owner" }) });
    renderMembership(ctx());
    expect(await screen.findByRole("heading", { name: "Membership" })).toBeInTheDocument();
    expect(await screen.findByText("Alice Owner")).toBeInTheDocument();
    expect(screen.getByText("Carol Member")).toBeInTheDocument();
    // The closed role vocabulary renders (as the current value of the role control).
    expect(screen.getByRole("combobox", { name: "Role for Carol Member" })).toHaveTextContent("Member");
  });

  it("adds an existing account through the API", async () => {
    const user = setupUser();
    stubApi({ roster: twoOwnerRoster(), self: membership({ user_id: 2, role: "owner" }) });
    renderMembership(ctx());
    await screen.findByText("Alice Owner");

    await user.click(screen.getByRole("button", { name: "Add member" }));
    await user.type(await screen.findByLabelText("Email"), "dave@example.com");
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Add member" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        `/workspaces/${WS}/memberships/`,
        expect.objectContaining({ method: "POST", body: { email: "dave@example.com", role: "member" } }),
      ),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(await screen.findByText("dave@example.com")).toBeInTheDocument();
  });

  it("changes a member's role through the API", async () => {
    const user = setupUser();
    stubApi({ roster: twoOwnerRoster(), self: membership({ user_id: 2, role: "owner" }) });
    renderMembership(ctx());
    await screen.findByText("Carol Member");

    await user.click(screen.getByRole("combobox", { name: "Role for Carol Member" }));
    await user.click(await screen.findByRole("option", { name: "Admin" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        `/workspaces/${WS}/memberships/3/role/`,
        expect.objectContaining({ method: "POST", body: { role: "admin" } }),
      ),
    );
    // Effect: the onSuccess roster invalidation refetches and the row reflects
    // the new role. Fails if the invalidation is dropped or points at the wrong key.
    expect(await screen.findByRole("combobox", { name: "Role for Carol Member" })).toHaveTextContent("Admin");
  });

  it("removes another member after confirmation", async () => {
    const user = setupUser();
    stubApi({ roster: twoOwnerRoster(), self: membership({ user_id: 2, role: "owner" }) });
    renderMembership(ctx());
    const row = (await screen.findByText("Carol Member")).closest("tr") as HTMLElement;

    await user.click(within(row).getByRole("button", { name: "Remove" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        `/workspaces/${WS}/memberships/3/remove/`,
        expect.objectContaining({ method: "POST" }),
      ),
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.queryByText("Carol Member")).not.toBeInTheDocument());
  });

  it("offers Leave (not Remove) on the caller's own row and posts to leave", async () => {
    const user = setupUser();
    stubApi({ roster: twoOwnerRoster(), self: membership({ user_id: 2, display_name: "Bob Owner", role: "owner" }) });
    renderMembership(ctx());
    const ownRow = (await screen.findByText("Bob Owner")).closest("tr") as HTMLElement;

    expect(within(ownRow).queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
    await user.click(within(ownRow).getByRole("button", { name: "Leave" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Leave" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        `/workspaces/${WS}/memberships/leave/`,
        expect.objectContaining({ method: "POST" }),
      ),
    );
    // Effect: onSuccess closes the confirm dialog (regresses if the callback is dropped).
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("shows the last-owner invariant and disables removing/demoting the sole owner", async () => {
    stubApi({
      roster: [
        membership({ user_id: 1, display_name: "Alice Owner", role: "owner" }),
        membership({ user_id: 3, display_name: "Carol Member", role: "member" }),
      ],
      self: membership({ user_id: 1, display_name: "Alice Owner", role: "owner" }),
    });
    renderMembership(ctx());
    expect(await screen.findByText("This workspace has a single owner")).toBeInTheDocument();

    // The sole owner is the caller: Leave is present but disabled (cannot leave as last owner).
    const ownerRow = screen.getByText("Alice Owner").closest("tr") as HTMLElement;
    expect(within(ownerRow).getByRole("button", { name: "Leave" })).toBeDisabled();
    // The sole owner's role is shown as static text, not an editable control (no demote).
    expect(within(ownerRow).queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("surfaces a server last_owner_required conflict and keeps the dialog open", async () => {
    const user = setupUser();
    stubApi({
      roster: twoOwnerRoster(),
      self: membership({ user_id: 2, role: "owner" }),
      overrides: (path, method) =>
        path === `/workspaces/${WS}/memberships/1/remove/` && method === "POST"
          ? Promise.reject(new ApiError(409, { code: "last_owner_required", message: "A workspace must keep an owner." }))
          : undefined,
    });
    renderMembership(ctx());
    const row = (await screen.findByText("Alice Owner")).closest("tr") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Remove" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));

    expect(await within(dialog).findByText("A workspace must keep an owner.")).toBeInTheDocument();
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });

  it("hides management actions the advertised capabilities do not include", async () => {
    stubApi({ roster: twoOwnerRoster(), self: membership({ user_id: 2, role: "owner" }) });
    // Roster-read only: can view but not add, change role, or remove.
    renderMembership(ctx({ role: "admin", capabilities: ["read_members"] }));
    await screen.findByText("Carol Member");

    expect(screen.queryByRole("button", { name: "Add member" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Role for Carol Member" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
  });

  it("renders a denied state when the roster is forbidden", async () => {
    stubApi({
      roster: twoOwnerRoster(),
      overrides: (path, method) =>
        path === `/workspaces/${WS}/memberships/` && method === "GET"
          ? Promise.reject(new ApiError(403, { code: "forbidden", message: "no" }))
          : undefined,
    });
    renderMembership(ctx());
    expect(await screen.findByText("You do not have permission to view the membership roster")).toBeInTheDocument();
  });

  it("does not render identity-dependent actions until the caller's own membership resolves", async () => {
    // Self membership never resolves: the roster has loaded but the caller's
    // identity has not, so the table (and its Leave/Remove actions) must not
    // render — otherwise the caller's own row could show Remove instead of Leave.
    stubApi({
      roster: twoOwnerRoster(),
      overrides: (path, method) =>
        path === `/workspaces/${WS}/membership/` && method === "GET" ? new Promise<never>(() => {}) : undefined,
    });
    renderMembership(ctx());
    await screen.findByRole("heading", { name: "Membership" });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("Bob Owner")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Leave" })).not.toBeInTheDocument();
  });

  it("renders a bounded error when the caller's own membership cannot be established", async () => {
    stubApi({
      roster: twoOwnerRoster(),
      overrides: (path, method) =>
        path === `/workspaces/${WS}/membership/` && method === "GET"
          ? Promise.reject(new ApiError(500, { code: "error", message: "boom" }))
          : undefined,
    });
    renderMembership(ctx());
    expect(await screen.findByText("Could not confirm your membership")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Leave" })).not.toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    stubApi({ roster: twoOwnerRoster(), self: membership({ user_id: 2, role: "owner" }) });
    const { container } = renderMembership(ctx());
    await screen.findByText("Alice Owner");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

describe("WorkspaceMembershipPage — self-service (member)", () => {
  const memberCtx = ctx({ role: "member", capabilities: ["read_self_membership", "leave_workspace"] });

  it("shows an honest self-service state without the roster and lets the member leave", async () => {
    const user = setupUser();
    stubApi({ roster: [], self: membership({ user_id: 3, display_name: "Carol Member", role: "member" }) });
    renderMembership(memberCtx);

    expect(await screen.findByText("Your membership")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    // No roster fetch is attempted without read_members.
    expect(mockApi).not.toHaveBeenCalledWith(`/workspaces/${WS}/memberships/`, expect.anything());

    await user.click(screen.getByRole("button", { name: "Leave" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Leave" }));
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        `/workspaces/${WS}/memberships/leave/`,
        expect.objectContaining({ method: "POST" }),
      ),
    );
    // Effect: onSuccess closes the confirm dialog (regresses if the callback is dropped).
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("has no axe violations in the self-service state", async () => {
    stubApi({ roster: [], self: membership({ user_id: 3, role: "member" }) });
    const { container } = renderMembership(memberCtx);
    await screen.findByText("Your membership");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

describe("WorkspaceMembershipPage — no access", () => {
  it("renders an honest not-available state when no membership capability applies", async () => {
    stubApi({ roster: [] });
    renderMembership(ctx({ role: "member", capabilities: [] }));
    expect(await screen.findByText("Membership is not available")).toBeInTheDocument();
  });
});
