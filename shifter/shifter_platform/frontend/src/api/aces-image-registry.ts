/**
 * TanStack Query hooks for the ACES image registry API (#1566). Caching,
 * invalidation, and retry policy live here; components call these hooks and never
 * fetch directly. The SPA uses the canonical `/api/v1/cms/` DRF routes only, which
 * delegate to the single validated `engine.services` write path. The whole
 * surface is gated by SHIFTER_ACES_NATIVE_PROVISIONING server-side (404 when off).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type { AcesImageMapping, AcesImageMappingDisable, AcesImageMappingRegister } from "./types";

const BASE = "/cms/aces-image-mappings";

export const acesImageMappingKeys = {
  all: ["aces-image-mappings"] as const,
  list: (includeDisabled: boolean) => ["aces-image-mappings", "list", includeDisabled] as const,
};

export function useAcesImageMappings(includeDisabled = true) {
  return useQuery({
    queryKey: acesImageMappingKeys.list(includeDisabled),
    queryFn: ({ signal }) =>
      apiFetch<AcesImageMapping[]>(`${BASE}/`, { query: { include_disabled: includeDisabled }, signal }),
  });
}

export function useRegisterAcesImageMapping() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AcesImageMappingRegister) => apiFetch<AcesImageMapping>(`${BASE}/`, { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: acesImageMappingKeys.all }),
  });
}

export function useDisableAcesImageMapping() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AcesImageMappingDisable) =>
      apiFetch<AcesImageMapping>(`${BASE}/disable/`, { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: acesImageMappingKeys.all }),
  });
}
