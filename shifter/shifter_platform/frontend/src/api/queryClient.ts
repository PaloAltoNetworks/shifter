import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "./errors";

/**
 * TanStack Query configuration encoding the ADR-029 retry/polling rules:
 * idempotent GETs retry with bounded backoff (never on 4xx); mutations never
 * auto-retry and surface the error for explicit user action.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status < 500) {
            return false;
          }
          return failureCount < 2;
        },
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
        refetchOnWindowFocus: false,
        staleTime: 15_000,
      },
      mutations: { retry: 0 },
    },
  });
}
