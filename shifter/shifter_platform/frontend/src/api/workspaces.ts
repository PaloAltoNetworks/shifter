/**
 * TanStack Query hooks for the workspace lifecycle API (#1940, PLAT-233). All
 * caching, invalidation, and retry policy live here; components call these hooks
 * and never fetch directly. Every call goes to the canonical `/api/v1/workspaces/`
 * DRF surface — the authoritative organization-admin / workspace-role authority
 * and audit boundary. Workspaces are addressed by their public UUID only, and
 * mutations never auto-retry (see `createQueryClient`).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import { principalContextKeys } from "./principalContext";
import type {
  CreateWorkspaceRequest,
  TransferWorkspaceOwnershipRequest,
  Workspace,
  WorkspaceEgressPolicy,
  WorkspaceQuota,
} from "./types";

export interface WorkspaceListFilters {
  organizationUuid: string;
  includeArchived?: boolean;
  search?: string;
}

export const workspaceKeys = {
  all: ["workspaces", "lifecycle"] as const,
  list: (filters: WorkspaceListFilters) => ["workspaces", "lifecycle", "list", filters] as const,
  detail: (uuid: string) => ["workspaces", "lifecycle", "detail", uuid] as const,
  quota: (uuid: string) => ["workspaces", "lifecycle", "quota", uuid] as const,
};

function invalidateWorkspaces(queryClient: ReturnType<typeof useQueryClient>, uuid?: string) {
  // A mutation can move a workspace between the active and archived lists and
  // change its detail, so invalidate the whole lifecycle key family.
  queryClient.invalidateQueries({ queryKey: workspaceKeys.all });
  if (uuid) {
    queryClient.invalidateQueries({ queryKey: workspaceKeys.detail(uuid) });
  }
  // The console switcher and workspace-scope layout resolve the selected
  // workspace from the principal-context membership snapshot, so a create,
  // rename, or archive/restore must refresh it too — otherwise a just-created
  // workspace resolves as "not found" until a manual reload.
  queryClient.invalidateQueries({ queryKey: principalContextKeys.all });
}

export function useWorkspaces(filters: WorkspaceListFilters, enabled = true) {
  return useQuery({
    queryKey: workspaceKeys.list(filters),
    enabled: enabled && Boolean(filters.organizationUuid),
    queryFn: ({ signal }) =>
      apiFetch<Workspace[]>("/workspaces/", {
        signal,
        query: {
          organization: filters.organizationUuid,
          include_archived: filters.includeArchived ? true : undefined,
          search: filters.search || undefined,
        },
      }),
  });
}

export function useWorkspace(uuid: string, enabled = true) {
  return useQuery({
    queryKey: workspaceKeys.detail(uuid),
    enabled: enabled && Boolean(uuid),
    queryFn: ({ signal }) => apiFetch<Workspace>(`/workspaces/${uuid}/`, { signal }),
  });
}

export function useWorkspaceQuota(uuid: string, enabled = true) {
  return useQuery({
    queryKey: workspaceKeys.quota(uuid),
    enabled: enabled && Boolean(uuid),
    queryFn: ({ signal }) => apiFetch<WorkspaceQuota>(`/workspaces/${uuid}/quota/`, { signal }),
  });
}

export function useCreateWorkspace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateWorkspaceRequest) =>
      apiFetch<Workspace>("/workspaces/", { method: "POST", body }),
    onSuccess: (data) => {
      queryClient.setQueryData(workspaceKeys.detail(data.uuid), data);
      invalidateWorkspaces(queryClient);
    },
  });
}

export function useRenameWorkspace(uuid: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch<Workspace>(`/workspaces/${uuid}/`, { method: "PATCH", body: { name } }),
    onSuccess: (data) => {
      queryClient.setQueryData(workspaceKeys.detail(uuid), data);
      invalidateWorkspaces(queryClient);
    },
  });
}

export function useArchiveWorkspace(uuid: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<Workspace>(`/workspaces/${uuid}/archive/`, { method: "POST" }),
    onSuccess: (data) => {
      queryClient.setQueryData(workspaceKeys.detail(uuid), data);
      invalidateWorkspaces(queryClient);
    },
  });
}

export function useRestoreWorkspace(uuid: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<Workspace>(`/workspaces/${uuid}/restore/`, { method: "POST" }),
    onSuccess: (data) => {
      queryClient.setQueryData(workspaceKeys.detail(uuid), data);
      invalidateWorkspaces(queryClient);
    },
  });
}

export function useSetWorkspaceEgressPolicy(uuid: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (egressPolicy: WorkspaceEgressPolicy) =>
      apiFetch<Workspace>(`/workspaces/${uuid}/egress-policy/`, {
        method: "PUT",
        body: { egress_policy: egressPolicy },
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(workspaceKeys.detail(uuid), data);
      invalidateWorkspaces(queryClient, uuid);
    },
  });
}

export function useTransferWorkspaceOwnership(uuid: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TransferWorkspaceOwnershipRequest) =>
      apiFetch<Workspace>(`/workspaces/${uuid}/transfer/`, { method: "POST", body }),
    onSuccess: (data) => {
      queryClient.setQueryData(workspaceKeys.detail(uuid), data);
      invalidateWorkspaces(queryClient);
    },
  });
}
