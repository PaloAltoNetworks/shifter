import type { ReactNode } from "react";

import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { principalContextKeys } from "./principalContext";
import { useArchiveWorkspace, useCreateWorkspace, workspaceKeys } from "./workspaces";

const mockApi = vi.mocked(apiFetch);

function makeClientWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  function wrapper({ children }: Readonly<{ children: ReactNode }>) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, wrapper };
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("workspace mutations", () => {
  it("useCreateWorkspace refreshes the lifecycle family and the principal-context snapshot", async () => {
    // Regression: without the principal-context invalidation, a freshly created
    // workspace resolves as "not found" in the console scope layout until reload.
    mockApi.mockResolvedValue({ uuid: "ws-1", name: "New" });
    const { client, wrapper } = makeClientWrapper();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCreateWorkspace(), { wrapper });
    result.current.mutate({ organization_uuid: "org-1", name: "New" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidate).toHaveBeenCalledWith({ queryKey: workspaceKeys.all });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: principalContextKeys.all });
  });

  it("useArchiveWorkspace also refreshes the principal-context snapshot", async () => {
    mockApi.mockResolvedValue({ uuid: "ws-1", name: "New", is_archived: true });
    const { client, wrapper } = makeClientWrapper();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useArchiveWorkspace("ws-1"), { wrapper });
    result.current.mutate();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidate).toHaveBeenCalledWith({ queryKey: principalContextKeys.all });
  });
});
