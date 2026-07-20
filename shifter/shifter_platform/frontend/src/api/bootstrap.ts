import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type { Bootstrap } from "./types";

export const bootstrapKey = ["bootstrap"] as const;

/**
 * Load the SPA session bootstrap payload once (principal, permission flags,
 * feature flags). Retries are disabled: a failure here (401/expired session)
 * should surface immediately so the app can redirect to login.
 */
export function useBootstrap() {
  return useQuery({
    queryKey: bootstrapKey,
    queryFn: ({ signal }) => apiFetch<Bootstrap>("/bootstrap/", { signal }),
    retry: false,
    staleTime: Infinity,
  });
}
