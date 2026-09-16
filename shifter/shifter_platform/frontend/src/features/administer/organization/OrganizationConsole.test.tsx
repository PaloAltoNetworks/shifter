import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";

import { ApiError } from "@/api/errors";
import type { PrincipalWorkspaceContext } from "@/api/types";
import { setupUser } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { ConsoleSlotPage } from "./ConsoleSlotPage";
import { OrganizationConsoleLayout } from "./OrganizationConsoleLayout";
import { OrganizationOverviewPage } from "./OrganizationOverviewPage";
import { WorkspaceScopeLayout } from "./WorkspaceScopeLayout";
import { WORKSPACE_SURFACES } from "./surfaces";

const mockApi = vi.mocked(apiFetch);

function ctx(overrides: Partial<PrincipalWorkspaceContext> = {}): PrincipalWorkspaceContext {
  return {
    organization: { uuid: "org-1", name: "Acme" },
    workspace_uuid: "11111111-1111-1111-1111-111111111111",
    workspace_name: "Blue",
    is_personal: false,
    role: "owner",
    capabilities: ["read_members", "add_member"],
    ...overrides,
  };
}

function page(results: PrincipalWorkspaceContext[]) {
  return { count: results.length, next: null, previous: null, results };
}

function renderConsole(initialEntries: string[]) {
  const router = createMemoryRouter(
    [
      {
        path: "/administer/organization",
        element: <OrganizationConsoleLayout />,
        children: [
          { index: true, element: <OrganizationOverviewPage /> },
          { path: "settings", element: <ConsoleSlotPage title="Organization settings" /> },
          {
            path: "workspaces/:workspaceUuid",
            element: <WorkspaceScopeLayout />,
            children: [
              { index: true, element: <ConsoleSlotPage title="Workspace overview" /> },
              ...WORKSPACE_SURFACES.map((surface) => ({
                path: surface.key,
                element: <ConsoleSlotPage title={surface.label} />,
              })),
            ],
          },
        ],
      },
    ],
    { initialEntries },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("OrganizationConsoleLayout", () => {
  it("renders the switcher and overview for a staff caller with workspaces", async () => {
    mockApi.mockResolvedValue(page([ctx()]));
    renderConsole(["/administer/organization"]);
    expect(await screen.findByRole("combobox", { name: "Select workspace" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Organization" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Acme" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Blue/ })).toBeInTheDocument();
  });

  it("aggregates every context page so no workspace is dropped from the switcher", async () => {
    const first = ctx({ workspace_uuid: "11111111-1111-1111-1111-111111111111", workspace_name: "Blue" });
    const second = ctx({
      workspace_uuid: "22222222-2222-2222-2222-222222222222",
      workspace_name: "Green",
      organization: { uuid: "org-2", name: "Beta" },
    });
    // Page 1 advertises a next page; the hook must follow it to page 2.
    mockApi
      .mockResolvedValueOnce({ count: 2, next: "http://x/api/v1/workspaces/context/?page=2", previous: null, results: [first] })
      .mockResolvedValueOnce({ count: 2, next: null, previous: null, results: [second] });
    renderConsole(["/administer/organization"]);
    expect(await screen.findByRole("link", { name: /Blue/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Green/ })).toBeInTheDocument();
    expect(mockApi).toHaveBeenCalledTimes(2);
  });

  it("shows an honest empty state when the caller has no workspaces", async () => {
    mockApi.mockResolvedValue(page([]));
    renderConsole(["/administer/organization"]);
    expect(await screen.findByText("No workspaces yet")).toBeInTheDocument();
  });

  it("renders a staff-only denied state on 403", async () => {
    mockApi.mockRejectedValue(new ApiError(403, { code: "forbidden", message: "no" }));
    renderConsole(["/administer/organization"]);
    expect(await screen.findByText("You do not have access to the organization console")).toBeInTheDocument();
  });

  it("renders a generic error state on failure", async () => {
    mockApi.mockRejectedValue(new ApiError(500, { code: "error", message: "boom" }));
    renderConsole(["/administer/organization"]);
    expect(await screen.findByText("Could not load organization context")).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue(page([ctx()]));
    const { container } = renderConsole(["/administer/organization"]);
    await screen.findByRole("link", { name: /Blue/ });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

describe("WorkspaceScopeLayout", () => {
  it("resolves a deep-linked workspace UUID and shows its capability-aware nav", async () => {
    mockApi.mockResolvedValue(page([ctx()]));
    renderConsole(["/administer/organization/workspaces/11111111-1111-1111-1111-111111111111"]);
    expect(await screen.findByRole("heading", { name: "Acme / Blue" })).toBeInTheDocument();
    // Owner has read_members → membership is a link.
    expect(screen.getByRole("link", { name: "Membership" })).toBeInTheDocument();
  });

  it("keeps membership reachable for a member via self-service", async () => {
    mockApi.mockResolvedValue(page([ctx({ role: "member", capabilities: ["read_self_membership", "leave_workspace"] })]));
    renderConsole(["/administer/organization/workspaces/11111111-1111-1111-1111-111111111111"]);
    await screen.findByRole("heading", { name: "Acme / Blue" });
    // A member lacks read_members but may leave → membership stays a link (self-service).
    expect(screen.getByRole("link", { name: "Membership" })).toBeInTheDocument();
  });

  it("disables a surface the workspace role does not permit", async () => {
    mockApi.mockResolvedValue(page([ctx({ role: "member", capabilities: ["read_self_membership"] })]));
    renderConsole(["/administer/organization/workspaces/11111111-1111-1111-1111-111111111111"]);
    await screen.findByRole("heading", { name: "Acme / Blue" });
    // Neither read_members nor leave_workspace → membership is present but not a link.
    expect(screen.queryByRole("link", { name: "Membership" })).not.toBeInTheDocument();
    expect(screen.getByText("Membership")).toHaveAttribute("aria-disabled", "true");
  });

  it("shows a not-found state for a stale/unknown workspace UUID", async () => {
    mockApi.mockResolvedValue(page([ctx()]));
    renderConsole(["/administer/organization/workspaces/99999999-9999-9999-9999-999999999999"]);
    expect(await screen.findByText("Workspace not found")).toBeInTheDocument();
  });

  it("switches workspace via the switcher and updates the URL scope", async () => {
    const user = setupUser();
    mockApi.mockResolvedValue(
      page([
        ctx(),
        ctx({ workspace_uuid: "22222222-2222-2222-2222-222222222222", workspace_name: "Green", organization: { uuid: "org-2", name: "Beta" } }),
      ]),
    );
    renderConsole(["/administer/organization"]);
    await screen.findByRole("combobox", { name: "Select workspace" });
    await user.click(screen.getByRole("combobox", { name: "Select workspace" }));
    await user.click(await screen.findByRole("option", { name: "Beta / Green" }));
    expect(await screen.findByRole("heading", { name: "Beta / Green" })).toBeInTheDocument();
  });
});
