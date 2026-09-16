/**
 * TanStack Query hook for the current-principal organization/workspace context
 * (#1938, PLAT-231). The organization admin console shell and switcher read the
 * caller's existing workspace memberships from the canonical, staff-session-only
 * `/api/v1/workspaces/context/` surface — the authoritative projection boundary.
 * Components call this hook and never fetch directly; `role`/`capabilities` are
 * advisory display data and the resource endpoints reauthorize every operation.
 *
 * The endpoint is page-number paginated, but the console needs the caller's
 * *complete* membership set — a partial set would drop workspaces from the
 * switcher and render valid deep links as "not found". The hook therefore
 * follows the pagination cursor to the end and returns the aggregated list.
 */
import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type { PaginatedPrincipalWorkspaceContextList, PrincipalWorkspaceContext } from "./types";

export const principalContextKeys = {
  all: ["workspaces", "principal-context"] as const,
};

async function fetchAllWorkspaceContexts(signal: AbortSignal): Promise<PrincipalWorkspaceContext[]> {
  const contexts: PrincipalWorkspaceContext[] = [];
  let page: number | undefined;
  // Follow the page-number cursor until the server reports no further page, so
  // the caller's whole membership set reaches the console (no silent truncation).
  for (;;) {
    const response = await apiFetch<PaginatedPrincipalWorkspaceContextList>("/workspaces/context/", {
      signal,
      query: { page },
    });
    contexts.push(...response.results);
    if (!response.next) {
      return contexts;
    }
    page = (page ?? 1) + 1;
  }
}

export function usePrincipalContext() {
  return useQuery({
    queryKey: principalContextKeys.all,
    queryFn: ({ signal }) => fetchAllWorkspaceContexts(signal),
  });
}
