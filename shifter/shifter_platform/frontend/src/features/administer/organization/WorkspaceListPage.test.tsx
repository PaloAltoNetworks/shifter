import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { axe } from "vitest-axe";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";

import { ApiError } from "@/api/errors";
import type { OrganizationProfile, Workspace } from "@/api/types";
import { setupUser } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { WorkspaceListPage } from "./WorkspaceListPage";

const mockApi = vi.mocked(apiFetch);

function org(overrides: Partial<OrganizationProfile> = {}): OrganizationProfile {
  return {
    uuid: "org-1",
    name: "Acme",
    description: "",
    support_email: "",
    support_url: "",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function workspace(overrides: Partial<Workspace> = {}): Workspace {
  return {
    uuid: "11111111-1111-1111-1111-111111111111",
    organization_uuid: "org-1",
    organization_name: "Acme",
    name: "Blue",
    is_personal: false,
    is_archived: false,
    archived_at: null,
    egress_policy: "status-quo",
    created_at: "2026-02-01T00:00:00Z",
    updated_at: "2026-02-01T00:00:00Z",
    ...overrides,
  };
}

function orgPage(results: OrganizationProfile[]) {
  return { count: results.length, next: null, previous: null, results };
}

/** Route apiFetch by path/method: organizations, workspace list, and create. */
function stubApi({
  orgs,
  workspaces,
  listError,
}: {
  orgs: OrganizationProfile[];
  workspaces?: Workspace[];
  listError?: ApiError;
}) {
  const list = workspaces ?? [];
  mockApi.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === "/workspaces/organizations/") return Promise.resolve(orgPage(orgs));
    if (path === "/workspaces/" && options?.method === "POST") {
      const created = workspace({ uuid: "22222222-2222-2222-2222-222222222222", name: "Created" });
      list.push(created);
      return Promise.resolve(created);
    }
    if (path === "/workspaces/") {
      if (listError) return Promise.reject(listError);
      return Promise.resolve(list);
    }
    return Promise.reject(new ApiError(404, { code: "not_found", message: "nope" }));
  });
}

function renderList(initialEntries: string[] = ["/administer/organization/workspaces"]) {
  const router = createMemoryRouter(
    [
      { path: "/administer/organization/workspaces", element: <WorkspaceListPage /> },
      { path: "/administer/organization/workspaces/:workspaceUuid", element: <div>scope</div> },
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

describe("WorkspaceListPage", () => {
  it("lists the workspaces of the only administrable organization", async () => {
    stubApi({ orgs: [org()], workspaces: [workspace()] });
    renderList();
    expect(await screen.findByRole("link", { name: "Blue" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Workspaces" })).toBeInTheDocument();
  });

  it("shows an honest empty state when the organization has no workspaces", async () => {
    stubApi({ orgs: [org()], workspaces: [] });
    renderList();
    expect(await screen.findByText("No workspaces yet")).toBeInTheDocument();
  });

  it("renders a denied state when the workspace list is forbidden", async () => {
    stubApi({ orgs: [org()], listError: new ApiError(403, { code: "forbidden", message: "no" }) });
    renderList();
    expect(await screen.findByText("You do not have permission to view these workspaces")).toBeInTheDocument();
  });

  it("shows the organization chooser when several are administrable", async () => {
    stubApi({ orgs: [org(), org({ uuid: "org-2", name: "Beta" })], workspaces: [workspace()] });
    renderList();
    expect(await screen.findByRole("combobox", { name: "Select organization" })).toBeInTheDocument();
  });

  it("marks an archived workspace with an archived badge", async () => {
    stubApi({ orgs: [org()], workspaces: [workspace({ is_archived: true, name: "Old" })] });
    renderList();
    await screen.findByRole("link", { name: "Old" });
    expect(screen.getByText("Archived")).toBeInTheDocument();
  });

  it("creates a workspace through the API", async () => {
    const user = setupUser();
    stubApi({ orgs: [org()], workspaces: [workspace()] });
    renderList();
    await screen.findByRole("link", { name: "Blue" });

    await user.click(screen.getByRole("button", { name: "Create workspace" }));
    await user.type(await screen.findByLabelText("Workspace name"), "Created");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        "/workspaces/",
        expect.objectContaining({ method: "POST", body: { organization_uuid: "org-1", name: "Created" } }),
      ),
    );
    // Success effect: onSuccess closes the create dialog and the invalidated list
    // refetch surfaces the new workspace row.
    expect(await screen.findByRole("link", { name: "Created" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("has no axe violations when loaded", async () => {
    stubApi({ orgs: [org()], workspaces: [workspace()] });
    const { container } = renderList();
    await screen.findByRole("link", { name: "Blue" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
