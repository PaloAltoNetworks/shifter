import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type { DashboardSummary } from "./types";

export const dashboardSummaryKey = ["dashboard", "summary"] as const;

/**
 * Load the operational dashboard summary for the platform home surface (#1369).
 *
 * Bounded composition of existing domain facts (active range/event, risk load).
 * A short stale window keeps the landing snappy without going stale; a single
 * bounded retry tolerates a transient blip without hammering on a real outage.
 */
export function useDashboardSummary() {
  return useQuery({
    queryKey: dashboardSummaryKey,
    queryFn: ({ signal }) => apiFetch<DashboardSummary>("/dashboard/summary/", { signal }),
    staleTime: 30_000,
    retry: 1,
  });
}
