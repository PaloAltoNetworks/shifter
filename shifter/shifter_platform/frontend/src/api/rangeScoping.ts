/**
 * TanStack Query hooks for range-to-workspace scope administration (#1944, PLAT-237).
 * All caching, invalidation, and retry policy live here; components call these
 * hooks and never fetch directly. Every call goes to the canonical
 * `/api/v1/cms/` DRF surface — the authoritative staff + workspace-role authority
 * and `shared.audit` boundary. Ranges are addressed by their public request UUID
 * and workspaces by their public UUID; the mutation never auto-retries (see
 * `createQueryClient`) because a scope move is sensitive, audited, and may race.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type { PaginatedRangeScopeBindingList, RangeWorkspaceRebindResult } from "./types";

export interface RangeScopeFilters {
  page?: number;
}

export const rangeScopingKeys = {
  all: ["cms", "range-scoping"] as const,
  list: (workspaceUuid: string, filters: RangeScopeFilters) =>
    ["cms", "range-scoping", "list", workspaceUuid, filters] as const,
};

/** Paginated ranges scoped to a workspace (staff + owner/admin, server-enforced). */
export function useWorkspaceRangeScopeBindings(
  workspaceUuid: string,
  filters: RangeScopeFilters = {},
  enabled = true,
) {
  return useQuery({
    queryKey: rangeScopingKeys.list(workspaceUuid, filters),
    enabled: enabled && Boolean(workspaceUuid),
    queryFn: ({ signal }) =>
      apiFetch<PaginatedRangeScopeBindingList>(`/cms/workspaces/${workspaceUuid}/range-scoping/`, {
        signal,
        query: { page: filters.page },
      }),
  });
}

export interface RebindRangeWorkspaceVariables {
  requestId: string;
  targetWorkspaceUuid: string;
}

/** Reassign a range's workspace scope to a target workspace (both scopes reauthorized server-side). */
export function useRebindRangeWorkspace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ requestId, targetWorkspaceUuid }: RebindRangeWorkspaceVariables) =>
      apiFetch<RangeWorkspaceRebindResult>(`/cms/ranges/${requestId}/workspace/`, {
        method: "POST",
        body: { target_workspace_uuid: targetWorkspaceUuid },
      }),
    // A moved range leaves the source listing and joins the target listing, so
    // invalidate every range-scoping list rather than only the source's.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: rangeScopingKeys.all }),
  });
}
