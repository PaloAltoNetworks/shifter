/**
 * TanStack Query hooks for the Risk Register API surface. All caching,
 * invalidation, and retry policy live here; components call these hooks and
 * never fetch directly.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type {
  Comment,
  PaginatedAuditLogList,
  PaginatedRiskList,
  PatchedRiskUpdate,
  Risk,
  RiskCreate,
  Severity,
  Status,
} from "./types";

export interface RiskFilters {
  severity?: Severity;
  status?: Status;
  includeDeleted?: boolean;
  page?: number;
}

export const riskKeys = {
  all: ["risks"] as const,
  list: (filters: RiskFilters) => ["risks", "list", filters] as const,
  detail: (id: number, includeDeleted: boolean) => ["risks", "detail", id, includeDeleted] as const,
  comments: (riskId: number, includeDeleted: boolean) => ["risks", "comments", riskId, includeDeleted] as const,
  audit: (riskId: number) => ["risks", "audit", riskId] as const,
};

function invalidateRisk(queryClient: ReturnType<typeof useQueryClient>, riskId?: number) {
  queryClient.invalidateQueries({ queryKey: riskKeys.all });
  if (riskId !== undefined) {
    queryClient.invalidateQueries({ queryKey: ["risks", "audit", riskId] });
  }
}

export function useRisks(filters: RiskFilters) {
  return useQuery({
    queryKey: riskKeys.list(filters),
    queryFn: ({ signal }) =>
      apiFetch<PaginatedRiskList>("/risks/", {
        signal,
        query: {
          severity: filters.severity,
          status: filters.status,
          include_deleted: filters.includeDeleted ? true : undefined,
          page: filters.page,
        },
      }),
  });
}

export function useRisk(id: number, includeDeleted = false, enabled = true) {
  return useQuery({
    queryKey: riskKeys.detail(id, includeDeleted),
    enabled,
    queryFn: ({ signal }) =>
      apiFetch<Risk>(`/risks/${id}/`, {
        signal,
        query: { include_deleted: includeDeleted ? true : undefined },
      }),
  });
}

export function useCreateRisk() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RiskCreate) => apiFetch<Risk>("/risks/", { method: "POST", body }),
    onSuccess: () => invalidateRisk(queryClient),
  });
}

export function useUpdateRisk(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PatchedRiskUpdate) => apiFetch<Risk>(`/risks/${id}/`, { method: "PATCH", body }),
    onSuccess: () => invalidateRisk(queryClient, id),
  });
}

export function useDeleteRisk() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/risks/${id}/`, { method: "DELETE" }),
    onSuccess: (_data, id) => invalidateRisk(queryClient, id),
  });
}

export function useRestoreRisk() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<Risk>(`/risks/${id}/restore/`, { method: "POST" }),
    onSuccess: (_data, id) => invalidateRisk(queryClient, id),
  });
}

export function useComments(riskId: number, includeDeleted = false) {
  return useQuery({
    queryKey: riskKeys.comments(riskId, includeDeleted),
    queryFn: ({ signal }) =>
      apiFetch<Comment[]>(`/risks/${riskId}/comments/`, {
        signal,
        query: { include_deleted: includeDeleted ? true : undefined },
      }),
  });
}

export function useAddComment(riskId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (content: string) =>
      apiFetch<Comment>(`/risks/${riskId}/comments/`, { method: "POST", body: { content } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["risks", "comments", riskId] });
      invalidateRisk(queryClient, riskId);
    },
  });
}

export function useDeleteComment(riskId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (commentId: number) =>
      apiFetch<void>(`/risks/${riskId}/comments/${commentId}/`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["risks", "comments", riskId] });
      invalidateRisk(queryClient, riskId);
    },
  });
}

export function useAudit(riskId: number, enabled = true) {
  return useQuery({
    queryKey: riskKeys.audit(riskId),
    enabled,
    queryFn: ({ signal }) =>
      apiFetch<PaginatedAuditLogList>("/audit/", {
        signal,
        query: { entity_type: "risk", entity_id: riskId },
      }),
  });
}

export type { AuditLog } from "./types";
