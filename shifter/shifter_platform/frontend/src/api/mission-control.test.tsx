import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { missionControlKeys, useCancelRange, useCurrentRange, useLaunchRange } from "./mission-control";

const mockApi = vi.mocked(apiFetch);

/** A provider wrapper bound to a fresh client the test can spy on. */
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

describe("missionControlKeys", () => {
  it("scopes every query key under the mission-control namespace", () => {
    expect(missionControlKeys.currentRange[0]).toBe("mission-control");
    expect(missionControlKeys.history[0]).toBe("mission-control");
    expect(missionControlKeys.agents[0]).toBe("mission-control");
    expect(missionControlKeys.scenarios[0]).toBe("mission-control");
    expect(missionControlKeys.ngfwList[0]).toBe("mission-control");
  });
});

describe("useCurrentRange", () => {
  it("reads the current-range endpoint", async () => {
    mockApi.mockResolvedValue({
      has_range: false,
      range: null,
      connection_urls: [],
      raes_projection: null,
      raes_participant_runtime: null,
      lifecycle: null,
      vpn_profile_available: false,
    });

    const { wrapper } = makeClientWrapper();
    const { result } = renderHook(() => useCurrentRange(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockApi).toHaveBeenCalledWith("/mission-control/range/", expect.objectContaining({}));
  });
});

describe("useCancelRange", () => {
  it("posts the request_id and invalidates the current-range + history caches on success", async () => {
    mockApi.mockResolvedValue({ success: true });

    const { client, wrapper } = makeClientWrapper();
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCancelRange(), { wrapper });
    result.current.mutate({ request_id: "abc-123" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockApi).toHaveBeenCalledWith("/mission-control/range/cancel/", {
      method: "POST",
      body: { request_id: "abc-123" },
    });
    // The onSuccess cache invalidation is the observable contract this hook
    // family (cancel/destroy/pause/resume share useRangeLifecycleMutation)
    // exists to guarantee — deleting the onSuccess callback MUST fail this
    // test, otherwise the dashboard/history silently shows stale range state
    // after a lifecycle action (test-quality review, #1370).
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: missionControlKeys.currentRange });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: missionControlKeys.history });
    // Never auto-retries a destructive lifecycle mutation.
    expect(result.current.failureCount).toBe(0);
  });
});

describe("useLaunchRange", () => {
  it("invalidates the current-range + history caches on success", async () => {
    mockApi.mockResolvedValue({ success: true, range: {} });

    const { client, wrapper } = makeClientWrapper();
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useLaunchRange(), { wrapper });
    result.current.mutate({ scenario: "basic", agent_id: 1 });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: missionControlKeys.currentRange });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: missionControlKeys.history });
  });
});
