import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";

import { ApiError } from "@/api/errors";
import type { PrincipalWorkspaceContext, RangeScopeBinding } from "@/api/types";
import { setupUser } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { WorkspaceContextProvider } from "./WorkspaceContext";
import { WorkspaceRangeScopingPage } from "./WorkspaceRangeScopingPage";

const mockApi = vi.mocked(apiFetch);

const WS = "11111111-1111-1111-1111-111111111111";
const TARGET_WS = "22222222-2222-2222-2222-222222222222";
const REQUEST_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";

function ctx(overrides: Partial<PrincipalWorkspaceContext> = {}): PrincipalWorkspaceContext {
  return {
    organization: { uuid: "org-1", name: "Acme" },
    workspace_uuid: WS,
    workspace_name: "Blue",
    is_personal: false,
    role: "admin",
    capabilities: ["list_range_scope_bindings", "rebind_range_workspace"],
    ...overrides,
  };
}

function binding(overrides: Partial<RangeScopeBinding> = {}): RangeScopeBinding {
  return {
    request_id: REQUEST_ID,
    owner_id: 7,
    range_source: "mission_control",
    status: "ready",
    scenario_id: "basic",
    created_at: "2026-02-01T00:00:00Z",
    updated_at: "2026-02-01T00:00:00Z",
    expires_at: null,
    is_reassignable: true,
    ...overrides,
  };
}

function stubApi(rows: RangeScopeBinding[]) {
  mockApi.mockImplementation((path: string, options?: { method?: string; body?: unknown }) => {
    const method = options?.method ?? "GET";
    if (path === `/cms/workspaces/${WS}/range-scoping/` && method === "GET") {
      return Promise.resolve({ count: rows.length, next: null, previous: null, results: rows });
    }
    const rebindMatch = /^\/cms\/ranges\/([^/]+)\/workspace\/$/.exec(path);
    if (rebindMatch && method === "POST") {
      return Promise.resolve({ changed: true });
    }
    return Promise.reject(new ApiError(404, { code: "not_found", message: "nope" }));
  });
}

interface PagedOptions {
  method?: string;
  query?: { page?: number };
}

/** Serve two pages so a test can drive Next/Previous navigation. */
function stubPagedApi(pages: Record<number, RangeScopeBinding[]>, total: number) {
  mockApi.mockImplementation((path: string, options?: PagedOptions) => {
    const method = options?.method ?? "GET";
    if (path === `/cms/workspaces/${WS}/range-scoping/` && method === "GET") {
      const page = options?.query?.page ?? 1;
      return Promise.resolve({
        count: total,
        next: page < Object.keys(pages).length ? "http://x/?page=2" : null,
        previous: page > 1 ? "http://x/?page=1" : null,
        results: pages[page] ?? [],
      });
    }
    return Promise.reject(new ApiError(404, { code: "not_found", message: "nope" }));
  });
}

function renderPage(workspaces: PrincipalWorkspaceContext[], selected: PrincipalWorkspaceContext | null) {
  const router = createMemoryRouter(
    [
      {
        path: "/administer/organization/workspaces/:workspaceUuid/range-scoping",
        element: (
          <WorkspaceContextProvider workspaces={workspaces} selected={selected}>
            <WorkspaceRangeScopingPage />
          </WorkspaceContextProvider>
        ),
      },
    ],
    { initialEntries: [`/administer/organization/workspaces/${WS}/range-scoping`] },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

const source = ctx();
const target = ctx({ workspace_uuid: TARGET_WS, workspace_name: "Green" });

beforeEach(() => {
  mockApi.mockReset();
});

describe("WorkspaceRangeScopingPage", () => {
  it("renders the ranges scoped to the workspace", async () => {
    stubApi([binding()]);
    renderPage([source, target], source);

    expect(await screen.findByRole("heading", { name: "Range scoping" })).toBeInTheDocument();
    expect(await screen.findByText("basic")).toBeInTheDocument();
    expect(screen.getByText("mission_control")).toBeInTheDocument();
    // No range detail beyond the bounded projection is rendered.
    expect(screen.queryByText("range_spec")).not.toBeInTheDocument();
  });

  it("disables reassignment for a non-reassignable (CTF) range", async () => {
    stubApi([binding({ request_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", range_source: "ctf", is_reassignable: false })]);
    renderPage([source, target], source);

    const button = await screen.findByRole("button", { name: "Reassign" });
    expect(button).toBeDisabled();
  });

  it("reassigns a range to a target workspace through the API", async () => {
    const user = setupUser();
    stubApi([binding()]);
    renderPage([source, target], source);

    await screen.findByText("basic");
    await user.click(screen.getByRole("button", { name: "Reassign" }));

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("combobox", { name: "Target workspace" }));
    await user.click(await screen.findByRole("option", { name: "Green" }));
    await user.click(within(dialog).getByRole("button", { name: "Reassign" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        `/cms/ranges/${REQUEST_ID}/workspace/`,
        expect.objectContaining({ method: "POST", body: { target_workspace_uuid: TARGET_WS } }),
      ),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("navigates beyond the first page of ranges", async () => {
    const user = setupUser();
    const pageOne = binding({ request_id: "11111111-0000-0000-0000-000000000001", scenario_id: "page-one" });
    const pageTwo = binding({ request_id: "22222222-0000-0000-0000-000000000002", scenario_id: "page-two" });
    stubPagedApi({ 1: [pageOne], 2: [pageTwo] }, 2);
    renderPage([source, target], source);

    expect(await screen.findByText("page-one")).toBeInTheDocument();
    expect(screen.queryByText("page-two")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("page-two")).toBeInTheDocument();
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        `/cms/workspaces/${WS}/range-scoping/`,
        expect.objectContaining({ query: expect.objectContaining({ page: 2 }) }),
      ),
    );
  });

  it("has no obvious accessibility violations", async () => {
    stubApi([binding()]);
    const { container } = renderPage([source, target], source);
    await screen.findByText("basic");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
