import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PrincipalWorkspaceContext, WorkspaceInvitation } from "@/api/types";
import { setupUser } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { WorkspaceContextProvider } from "./WorkspaceContext";
import { WorkspaceInvitationsPage } from "./WorkspaceInvitationsPage";

const mockApi = vi.mocked(apiFetch);
const WS = "11111111-1111-1111-1111-111111111111";
const INVITE = "22222222-2222-4222-8222-222222222222";

function context(capabilities = ["read_invitations", "issue_invitation", "resend_invitation", "revoke_invitation"]): PrincipalWorkspaceContext {
  return {
    organization: { uuid: "33333333-3333-4333-8333-333333333333", name: "Acme" },
    workspace_uuid: WS,
    workspace_name: "Blue",
    is_personal: false,
    role: "owner",
    capabilities,
  };
}

function invitation(overrides: Partial<WorkspaceInvitation> = {}): WorkspaceInvitation {
  return {
    invitation_uuid: INVITE,
    workspace_uuid: WS,
    email: "new.member@example.com",
    role: "member",
    status: "pending",
    expires_at: "2026-08-19T12:00:00Z",
    created_at: "2026-08-12T12:00:00Z",
    updated_at: "2026-08-12T12:00:00Z",
    ...overrides,
  };
}

function renderPage(selected = context()) {
  const router = createMemoryRouter([
    {
      path: "/administer/organization/workspaces/:workspaceUuid/invitations",
      element: (
        <WorkspaceContextProvider workspaces={[selected]} selected={selected}>
          <WorkspaceInvitationsPage />
        </WorkspaceContextProvider>
      ),
    },
  ], { initialEntries: [`/administer/organization/workspaces/${WS}/invitations`] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
}

beforeEach(() => mockApi.mockReset());

describe("WorkspaceInvitationsPage", () => {
  it("lists invitation status without exposing a credential", async () => {
    mockApi.mockResolvedValue([invitation()]);
    renderPage();

    expect(await screen.findByRole("heading", { name: "Invitations" })).toBeInTheDocument();
    expect(screen.getByText("new.member@example.com")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
    expect(screen.queryByText(/token=/)).not.toBeInTheDocument();
  });

  it("issues and resends through the named invitation endpoints", async () => {
    const user = setupUser();
    mockApi.mockImplementation((_path: string, options?: { method?: string; body?: unknown }) => {
      if ((options?.method ?? "GET") === "GET") return Promise.resolve([invitation()]);
      return Promise.resolve(invitation());
    });
    renderPage();
    await screen.findByText("new.member@example.com");

    await user.click(screen.getByRole("button", { name: "Invite member" }));
    await user.type(screen.getByLabelText("Email"), "another@example.com");
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Send invitation" }));
    await user.click(screen.getByRole("button", { name: "Resend" }));

    await waitFor(() => expect(mockApi).toHaveBeenCalledWith(
      `/workspaces/${WS}/invitations/`,
      expect.objectContaining({ method: "POST", body: { email: "another@example.com", role: "member" } }),
    ));
    expect(mockApi).toHaveBeenCalledWith(
      `/workspaces/${WS}/invitations/${INVITE}/resend/`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("hides the surface when capabilities do not admit invitation reads", async () => {
    renderPage(context([]));
    expect(await screen.findByText("Invitations are not available")).toBeInTheDocument();
    expect(mockApi).not.toHaveBeenCalled();
  });
});
