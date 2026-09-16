import { describe, expect, it } from "vitest";

import { ApiError } from "./errors";
import { createQueryClient } from "./queryClient";

type RetryFn = (failureCount: number, error: unknown) => boolean;
type RetryDelayFn = (attempt: number) => number;

function apiError(status: number): ApiError {
  return new ApiError(status, { code: "err", message: "boom" });
}

describe("createQueryClient", () => {
  it("never retries an idempotent GET on a 4xx ApiError", () => {
    const retry = createQueryClient().getDefaultOptions().queries?.retry as RetryFn;
    expect(retry(0, apiError(400))).toBe(false);
    expect(retry(0, apiError(401))).toBe(false);
    expect(retry(0, apiError(404))).toBe(false);
  });

  it("retries a GET on a 5xx / network error up to a bounded count", () => {
    const retry = createQueryClient().getDefaultOptions().queries?.retry as RetryFn;
    expect(retry(0, apiError(500))).toBe(true);
    expect(retry(1, new Error("network"))).toBe(true);
    // failureCount === 2 stops the bounded backoff.
    expect(retry(2, new Error("network"))).toBe(false);
  });

  it("caps the retry backoff at 8s", () => {
    const retryDelay = createQueryClient().getDefaultOptions().queries?.retryDelay as RetryDelayFn;
    expect(retryDelay(0)).toBe(1000);
    expect(retryDelay(1)).toBe(2000);
    expect(retryDelay(2)).toBe(4000);
    expect(retryDelay(10)).toBe(8000);
  });

  it("never auto-retries mutations (ADR-029: surface for explicit user action)", () => {
    expect(createQueryClient().getDefaultOptions().mutations?.retry).toBe(0);
  });

  it("disables refetch-on-focus and sets a bounded stale time", () => {
    const queries = createQueryClient().getDefaultOptions().queries;
    expect(queries?.refetchOnWindowFocus).toBe(false);
    expect(queries?.staleTime).toBe(15_000);
  });
});
