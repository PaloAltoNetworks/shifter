import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type { components } from "./schema";

export type ModelSource = components["schemas"]["ModelSourceView"];
export type SourceConfiguration = components["schemas"]["ModelSourceConfiguration"];
export type SourceWrite = components["schemas"]["ModelSourceWrite"];
export const sourceKey = (organization: string) => ["model-sources", organization] as const;
export const sourceBase = (organization: string) => `/cms/organizations/${organization}/model-sources/`;

export function useModelSources(organization: string, available = false) {
  return useQuery({
    queryKey: [...sourceKey(organization), available ? "available" : "admin"], enabled: Boolean(organization),
    queryFn: ({ signal }) => apiFetch<components["schemas"]["ModelSourcePage"]>(
      sourceBase(organization) + (available ? "available/" : ""), { signal }),
  });
}

// Secret-bearing writes deliberately bypass mutation caches. The form owns
// transient input and clears it after every attempted submission.
export function saveModelSource(organization: string, body: SourceWrite, source?: ModelSource) {
  return apiFetch<ModelSource>(sourceBase(organization) + (source ? `${source.id}/` : ""), {
    method: source ? "PUT" : "POST", body: source ? { ...body, expected_revision: source.revision, enabled: source.enabled } : body,
  });
}

export function retireModelSourceCredentials(organization: string, source: string) {
  return apiFetch<{ retired: number }>(sourceBase(organization) + `${source}/retire-credentials/`, {
    method: "POST", body: {},
  });
}

export type ModelSourceSelection = components["schemas"]["ModelSourceSelection"];
export function useModelSourceOptions(scenario: string, workspace = "", purpose: "range" | "ctf" | "admin" = "range") {
  return useQuery({
    queryKey: ["model-source-options", purpose, workspace, scenario],
    queryFn: ({ signal }) => apiFetch<components["schemas"]["SourceOptions"]>("/cms/model-source-options/", {
      signal, query: { scenario, workspace: workspace || undefined, purpose },
    }),
  });
}

export type RangeModelSources = components["schemas"]["RangeModelSources"];
export const rangeSourceKey = (request: string) => ["range-model-sources", request] as const;
export function useModelRanges(organization: string, page: number) {
  return useQuery({ queryKey: ["model-ranges", organization, page], enabled: Boolean(organization),
    queryFn: ({ signal }) => apiFetch<components["schemas"]["ModelRangePage"]>(`/cms/organizations/${organization}/model-ranges/`,
      { signal, query: { page } }) });
}
export function useRangeModelSources(request: string) {
  return useQuery({ queryKey: rangeSourceKey(request), enabled: Boolean(request),
    queryFn: ({ signal }) => apiFetch<RangeModelSources>(`/cms/ranges/${request}/model-sources/`, { signal }),
    refetchInterval: (query) => query.state.data?.runtime.state === "refresh_pending" ? 5000 : false });
}
export function saveRangeModelSources(request: string, expectedRevision: number, selection: ModelSourceSelection) {
  return apiFetch<RangeModelSources>(`/cms/ranges/${request}/model-sources/`, {
    method: "PUT", body: { expected_revision: expectedRevision, selection },
  });
}

export function useModelSourceUsers(organization: string, search: string, page: number) {
  return useQuery({ queryKey: ["model-source-users", organization, search, page], enabled: Boolean(organization),
    queryFn: ({ signal }) => apiFetch<components["schemas"]["ModelSourceUserPage"]>(`/cms/organizations/${organization}/model-source-users/`,
      { signal, query: { search, page } }) });
}
