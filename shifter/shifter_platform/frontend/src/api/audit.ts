/**
 * TanStack Query hook for the administrator audit / activity-history API
 * (#1947, PLAT-240). All caching and retry policy live here; components call this
 * hook and never fetch directly. Every call goes to the canonical, staff-session
 * `/api/v1/audit/` DRF surface — the authoritative, deployment-global read over
 * the immutable `shared.audit` record (ADR-045/046-R7). The audit store has no
 * per-row workspace scope, so no workspace UUID filters or authorizes it.
 *
 * Types come from the generated OpenAPI contract (`AuditLog`,
 * `PaginatedAuditLogList` re-exported from `./types`); this module never
 * hand-copies an audit DTO. The filter object is normalized into the query key so
 * a refresh or shared link reproduces the same query with no local storage.
 */
import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type { PaginatedAuditLogList } from "./types";

/** The structured filter surface: event type (`action`), entity, actor, and time.
 *
 * `entityId` / `actorId` are carried as the raw query value, not a parsed number:
 * validation is the server's single responsibility (the DRF query serializer), so
 * a malformed id reaches the endpoint and returns the shared 400 rather than the
 * client silently dropping the filter and broadening the result. */
export interface AuditFilters {
  action?: string;
  entityType?: string;
  entityId?: string;
  actorType?: string;
  actorId?: string;
  requestId?: string;
  fromDate?: string;
  toDate?: string;
  page?: number;
}

export const auditKeys = {
  all: ["audit"] as const,
  list: (filters: AuditFilters) => ["audit", "list", filters] as const,
};

export function useAuditEvents(filters: AuditFilters) {
  return useQuery({
    queryKey: auditKeys.list(filters),
    queryFn: ({ signal }) =>
      apiFetch<PaginatedAuditLogList>("/audit/", {
        signal,
        query: {
          action: filters.action || undefined,
          entity_type: filters.entityType || undefined,
          entity_id: filters.entityId || undefined,
          actor_type: filters.actorType || undefined,
          actor_id: filters.actorId || undefined,
          request_id: filters.requestId || undefined,
          from_date: filters.fromDate || undefined,
          to_date: filters.toDate || undefined,
          page: filters.page,
        },
      }),
  });
}
