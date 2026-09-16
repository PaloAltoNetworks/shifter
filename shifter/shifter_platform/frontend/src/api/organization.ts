/**
 * TanStack Query hooks for the Organization profile & settings API (#1939,
 * PLAT-232). All caching and invalidation live here; components call these hooks
 * and never fetch directly. Every call goes to the canonical
 * `/api/v1/workspaces/organizations/{uuid}/` DRF surface — the authoritative
 * organization-admin authority and audit boundary (ADR-048). Organizations are
 * addressed by their public UUID only.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type {
  OrganizationProfile,
  OrganizationProfileUpdate,
  PaginatedOrganizationProfileList,
} from "./types";

export const organizationKeys = {
  all: ["workspaces", "organization"] as const,
  administrable: ["workspaces", "organization", "administrable"] as const,
  detail: (uuid: string) => ["workspaces", "organization", "detail", uuid] as const,
};

export function useAdministrableOrganizations() {
  return useQuery({
    queryKey: organizationKeys.administrable,
    queryFn: ({ signal }) =>
      apiFetch<PaginatedOrganizationProfileList>("/workspaces/organizations/", { signal }),
  });
}

export function useOrganizationProfile(uuid: string, enabled = true) {
  return useQuery({
    queryKey: organizationKeys.detail(uuid),
    enabled: enabled && Boolean(uuid),
    queryFn: ({ signal }) =>
      apiFetch<OrganizationProfile>(`/workspaces/organizations/${uuid}/`, { signal }),
  });
}

export function useUpdateOrganizationProfile(uuid: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (changes: OrganizationProfileUpdate) =>
      apiFetch<OrganizationProfile>(`/workspaces/organizations/${uuid}/`, {
        method: "PATCH",
        body: changes,
      }),
    onSuccess: (data) => {
      // The PATCH response is the authoritative fresh profile, so seed the cache
      // directly rather than forcing a redundant refetch.
      queryClient.setQueryData(organizationKeys.detail(uuid), data);
    },
  });
}
