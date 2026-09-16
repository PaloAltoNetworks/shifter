/**
 * TanStack Query hooks for the workspace membership & roles API (#1941, PLAT-234).
 * All caching, invalidation, and retry policy live here; components call these
 * hooks and never fetch directly. Every call goes to the canonical
 * `/api/v1/workspaces/{uuid}/memberships/` DRF surface — the authoritative
 * workspace-role authority and `shared.audit` boundary. Workspaces are addressed
 * by their public UUID and members by the server-provided `user_id`; mutations
 * never auto-retry (see `createQueryClient`) because membership changes are
 * sensitive, audited, and may race.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import { principalContextKeys } from "./principalContext";
import type {
  AddWorkspaceMemberRequest,
  ChangeWorkspaceMemberRoleRequest,
  WorkspaceMembership,
  WorkspaceRole,
} from "./types";

export const membershipKeys = {
  all: ["workspaces", "membership"] as const,
  roster: (uuid: string) => ["workspaces", "membership", "roster", uuid] as const,
  self: (uuid: string) => ["workspaces", "membership", "self", uuid] as const,
};

/** The full membership roster for a workspace (owner/admin only, server-enforced). */
export function useWorkspaceMemberships(uuid: string, enabled = true) {
  return useQuery({
    queryKey: membershipKeys.roster(uuid),
    enabled: enabled && Boolean(uuid),
    queryFn: ({ signal }) => apiFetch<WorkspaceMembership[]>(`/workspaces/${uuid}/memberships/`, { signal }),
  });
}

/** The caller's own membership, used to identify the caller's row in the roster. */
export function useSelfMembership(uuid: string, enabled = true) {
  return useQuery({
    queryKey: membershipKeys.self(uuid),
    enabled: enabled && Boolean(uuid),
    queryFn: ({ signal }) => apiFetch<WorkspaceMembership>(`/workspaces/${uuid}/membership/`, { signal }),
  });
}

function invalidateRoster(queryClient: ReturnType<typeof useQueryClient>, uuid: string) {
  queryClient.invalidateQueries({ queryKey: membershipKeys.roster(uuid) });
}

export function useAddWorkspaceMember(uuid: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AddWorkspaceMemberRequest) =>
      apiFetch<WorkspaceMembership>(`/workspaces/${uuid}/memberships/`, { method: "POST", body }),
    onSuccess: () => invalidateRoster(queryClient, uuid),
  });
}

export interface ChangeMemberRoleVariables {
  userId: number;
  role: WorkspaceRole;
}

export function useChangeWorkspaceMemberRole(uuid: string, selfUserId?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }: ChangeMemberRoleVariables) =>
      apiFetch<WorkspaceMembership>(`/workspaces/${uuid}/memberships/${userId}/role/`, {
        method: "POST",
        body: { role } satisfies ChangeWorkspaceMemberRoleRequest,
      }),
    onSuccess: (membership) => {
      invalidateRoster(queryClient, uuid);
      // A caller who changed its OWN role sees its capabilities shift, which can
      // also change the console's selected-workspace validity; refresh both the
      // self snapshot and the principal context so the shell re-derives them.
      if (membership.user_id === selfUserId) {
        queryClient.invalidateQueries({ queryKey: membershipKeys.self(uuid) });
        queryClient.invalidateQueries({ queryKey: principalContextKeys.all });
      }
    },
  });
}

export function useRemoveWorkspaceMember(uuid: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: number) =>
      apiFetch<WorkspaceMembership>(`/workspaces/${uuid}/memberships/${userId}/remove/`, { method: "POST" }),
    onSuccess: () => invalidateRoster(queryClient, uuid),
  });
}

export function useLeaveWorkspace(uuid: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<WorkspaceMembership>(`/workspaces/${uuid}/memberships/leave/`, { method: "POST" }),
    onSuccess: () => {
      // Leaving removes the caller from the workspace: its roster row, its self
      // membership, and its principal context (capabilities + whether this
      // workspace still resolves) all change.
      invalidateRoster(queryClient, uuid);
      queryClient.invalidateQueries({ queryKey: membershipKeys.self(uuid) });
      queryClient.invalidateQueries({ queryKey: principalContextKeys.all });
    },
  });
}
