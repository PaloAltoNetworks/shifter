/**
 * TanStack Query hooks for the RAES image registry API (#1566). Caching,
 * invalidation, and retry policy live here; components call these hooks and never
 * fetch directly. The SPA uses the canonical `/api/v1/cms/` DRF routes only, which
 * delegate to the single validated `engine.services` write path.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type { RaesImageMapping, RaesImageMappingDisable, RaesImageMappingRegister } from "./types";

const BASE = "/cms/raes-image-mappings";

export const raesImageMappingKeys = {
  all: ["raes-image-mappings"] as const,
  list: (includeDisabled: boolean) => ["raes-image-mappings", "list", includeDisabled] as const,
};

export function useRaesImageMappings(includeDisabled = true) {
  return useQuery({
    queryKey: raesImageMappingKeys.list(includeDisabled),
    queryFn: ({ signal }) =>
      apiFetch<RaesImageMapping[]>(`${BASE}/`, { query: { include_disabled: includeDisabled }, signal }),
  });
}

export function useRegisterRaesImageMapping() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RaesImageMappingRegister) => apiFetch<RaesImageMapping>(`${BASE}/`, { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: raesImageMappingKeys.all }),
  });
}

export function useDisableRaesImageMapping() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RaesImageMappingDisable) =>
      apiFetch<RaesImageMapping>(`${BASE}/disable/`, { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: raesImageMappingKeys.all }),
  });
}
