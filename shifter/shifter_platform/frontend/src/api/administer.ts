/**
 * TanStack Query hooks for the Administer user-administration API (#1373). All
 * caching, invalidation, and retry policy live here; components call these hooks
 * and never fetch directly. Every call goes to the canonical `/api/v1/administer/`
 * DRF surface — the authoritative permission and audit boundary.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type {
  AccountLifecycleAction,
  AdminUserDetail,
  OrganizerGrantResult,
  PaginatedAdminUserListItemList,
  MissionControlLeasePolicySettings,
  ReplaceMissionControlLeasePolicyRequest,
  ResetMissionControlLeasePolicyRequest,
  TransferOwnershipRequest,
  TransferOwnershipResult,
} from "./types";

export interface AdminUserFilters {
  search?: string;
  userType?: string;
  isActive?: boolean;
  accountOrigin?: string;
  includeDeleted?: boolean;
  page?: number;
}

export const administerKeys = {
  all: ["administer", "users"] as const,
  list: (filters: AdminUserFilters) => ["administer", "users", "list", filters] as const,
  detail: (id: number) => ["administer", "users", "detail", id] as const,
};

export const missionControlLeasePolicyKeys = {
  all: ["administer", "mission-control-lease-policy"] as const,
  settings: () => ["administer", "mission-control-lease-policy", "settings"] as const,
};

function invalidateMissionControlLeasePolicy(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: missionControlLeasePolicyKeys.all });
}

export function useMissionControlLeasePolicySettings() {
  return useQuery({
    queryKey: missionControlLeasePolicyKeys.settings(),
    queryFn: ({ signal }) =>
      apiFetch<MissionControlLeasePolicySettings>("/administer/mission-control/lease-policy/", { signal }),
  });
}

export function useReplaceTenantLeasePolicy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ReplaceMissionControlLeasePolicyRequest) =>
      apiFetch<MissionControlLeasePolicySettings>("/administer/mission-control/lease-policy/tenant/", {
        method: "PUT",
        body,
      }),
    retry: false,
    onSuccess: () => invalidateMissionControlLeasePolicy(queryClient),
  });
}

export function useResetTenantLeasePolicy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ResetMissionControlLeasePolicyRequest) =>
      apiFetch<MissionControlLeasePolicySettings>("/administer/mission-control/lease-policy/tenant/reset/", {
        method: "POST",
        body,
      }),
    retry: false,
    onSuccess: () => invalidateMissionControlLeasePolicy(queryClient),
  });
}

export function useReplaceGroupLeasePolicy(groupId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ReplaceMissionControlLeasePolicyRequest) =>
      apiFetch<MissionControlLeasePolicySettings>(`/administer/mission-control/lease-policy/groups/${groupId}/`, {
        method: "PUT",
        body,
      }),
    retry: false,
    onSuccess: () => invalidateMissionControlLeasePolicy(queryClient),
  });
}

export function useResetGroupLeasePolicy(groupId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ResetMissionControlLeasePolicyRequest) =>
      apiFetch<MissionControlLeasePolicySettings>(
        `/administer/mission-control/lease-policy/groups/${groupId}/reset/`,
        { method: "POST", body },
      ),
    retry: false,
    onSuccess: () => invalidateMissionControlLeasePolicy(queryClient),
  });
}

function invalidateUsers(queryClient: ReturnType<typeof useQueryClient>, id?: number) {
  queryClient.invalidateQueries({ queryKey: administerKeys.all });
  if (id !== undefined) {
    queryClient.invalidateQueries({ queryKey: administerKeys.detail(id) });
  }
}

export function useAdminUsers(filters: AdminUserFilters) {
  return useQuery({
    queryKey: administerKeys.list(filters),
    queryFn: ({ signal }) =>
      apiFetch<PaginatedAdminUserListItemList>("/administer/users/", {
        signal,
        query: {
          search: filters.search || undefined,
          user_type: filters.userType || undefined,
          is_active: filters.isActive,
          account_origin: filters.accountOrigin || undefined,
          include_deleted: filters.includeDeleted ? true : undefined,
          page: filters.page,
        },
      }),
  });
}

export function useAdminUser(id: number, enabled = true) {
  return useQuery({
    queryKey: administerKeys.detail(id),
    enabled,
    queryFn: ({ signal }) => apiFetch<AdminUserDetail>(`/administer/users/${id}/`, { signal }),
  });
}

export function useSetUserActive(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (isActive: boolean) =>
      apiFetch<AdminUserDetail>(`/administer/users/${id}/set-active/`, {
        method: "POST",
        body: { is_active: isActive },
      }),
    onSuccess: () => invalidateUsers(queryClient, id),
  });
}

export function useSoftDeleteUser(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<AdminUserDetail>(`/administer/users/${id}/delete/`, { method: "POST" }),
    onSuccess: () => invalidateUsers(queryClient, id),
  });
}

export function useGrantOrganizer(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<OrganizerGrantResult>(`/administer/users/${id}/grant-organizer/`, { method: "POST" }),
    onSuccess: () => invalidateUsers(queryClient, id),
  });
}

/**
 * Account lifecycle transition (activate / deactivate / suspend). The server
 * derives the allowed actions and reauthorizes every transition; the SPA never
 * reconstructs the transition policy.
 */
export function useAccountLifecycle(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (action: AccountLifecycleAction) =>
      apiFetch<AdminUserDetail>(`/administer/users/${id}/lifecycle/`, {
        method: "POST",
        body: { action },
      }),
    onSuccess: () => invalidateUsers(queryClient, id),
  });
}

/** Trigger a Django password-reset email for an eligible local, non-CTF account. */
export function useResetUserPassword(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<AdminUserDetail>(`/administer/users/${id}/reset-password/`, { method: "POST" }),
    onSuccess: () => invalidateUsers(queryClient, id),
  });
}

/** Transfer a departing user's owned ranges and/or workspaces to a replacement. */
export function useTransferOwnership(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TransferOwnershipRequest) =>
      apiFetch<TransferOwnershipResult>(`/administer/users/${id}/transfer-ownership/`, {
        method: "POST",
        body,
      }),
    onSuccess: () => invalidateUsers(queryClient, id),
  });
}
