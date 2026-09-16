import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";

import { ApiError } from "@/api/errors";
import type { WorkspaceQuota } from "@/api/types";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { WorkspaceQuotaPage } from "./WorkspaceQuotaPage";

const mockApi = vi.mocked(apiFetch);
const WS = "11111111-1111-1111-1111-111111111111";

function quota(overrides: Partial<WorkspaceQuota> = {}): WorkspaceQuota {
  return {
    workspace_uuid: WS,
    resources: [
      { resource: "concurrent_ranges", usage: 2, limit: 5, mode: "enforcing" },
      { resource: "member_seats", usage: 1, limit: null, mode: null },
    ],
    recent_decisions: [
      {
        resource: "concurrent_ranges",
        outcome: "rejected",
        limit: 5,
        mode: "enforcing",
        usage_before: 5,
        requested_delta: 1,
        reason_code: "hard_cap_exhausted",
        created_at: "2026-03-01T10:00:00Z",
      },
    ],
    ...overrides,
  } as WorkspaceQuota;
}

function stubApi(result: WorkspaceQuota | ApiError) {
  mockApi.mockImplementation((path: string) => {
    if (path === `/workspaces/${WS}/quota/`) {
      return result instanceof ApiError ? Promise.reject(result) : Promise.resolve(result);
    }
    return Promise.reject(new ApiError(404, { code: "not_found", message: "nope" }));
  });
}

function renderPage() {
  const router = createMemoryRouter(
    [{ path: "/administer/organization/workspaces/:workspaceUuid/quota", element: <WorkspaceQuotaPage /> }],
    { initialEntries: [`/administer/organization/workspaces/${WS}/quota`] },
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

describe("WorkspaceQuotaPage", () => {
  it("renders usage against limits and the unlimited resource", async () => {
    stubApi(quota());
    renderPage();
    expect(await screen.findByText("2 of 5 used")).toBeInTheDocument();
    expect(screen.getByText("Unlimited — no quota policy configured.")).toBeInTheDocument();
  });

  it("shows recent quota decisions with the applied outcome", async () => {
    stubApi(quota());
    renderPage();
    expect(await screen.findByText("Blocked")).toBeInTheDocument();
    expect(screen.getByText("5 / 5")).toBeInTheDocument();
  });

  it("renders a denied state on 403", async () => {
    stubApi(new ApiError(403, { code: "forbidden", message: "no" }));
    renderPage();
    expect(await screen.findByText("Quota is not available")).toBeInTheDocument();
  });
});
