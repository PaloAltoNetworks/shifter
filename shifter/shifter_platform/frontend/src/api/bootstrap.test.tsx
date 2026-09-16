import type { ReactNode } from "react";

import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { ApiError } from "./errors";
import { bootstrapKey, useBootstrap } from "./bootstrap";

const mockApi = vi.mocked(apiFetch);

/** A wrapper whose client keeps default retry, so the hook's own retry:false is
 * what is under test (not a client-level override). */
function wrapperFactory() {
  const client = new QueryClient();
  return function wrapper({ children }: Readonly<{ children: ReactNode }>) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("useBootstrap", () => {
  it("reads the /bootstrap/ endpoint under the bootstrap query key", async () => {
    mockApi.mockResolvedValue({ principal: { is_authenticated: true } });

    const { result } = renderHook(() => useBootstrap(), { wrapper: wrapperFactory() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockApi).toHaveBeenCalledWith("/bootstrap/", expect.objectContaining({}));
    expect(bootstrapKey).toEqual(["bootstrap"]);
  });

  it("does not retry on failure so an expired session surfaces immediately", async () => {
    mockApi.mockRejectedValue(new ApiError(401, { code: "unauth", message: "expired" }));

    const { result } = renderHook(() => useBootstrap(), { wrapper: wrapperFactory() });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(mockApi).toHaveBeenCalledTimes(1);
  });
});
