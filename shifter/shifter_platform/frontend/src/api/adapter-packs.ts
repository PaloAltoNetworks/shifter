import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type { components } from "./schema";

export type AdapterPack = components["schemas"]["RuntimePluginPack"];
export type AdapterPackDetail = components["schemas"]["RuntimePluginPackDetail"];
export type AdapterPackUpdate = components["schemas"]["RuntimePluginPackUpdate"];
export type AdapterTargetImageProfile = components["schemas"]["RuntimeTargetImageProfile"];
const key = (organization: string) => ["adapter-packs", organization] as const;
const base = (organization: string) => `/cms/organizations/${organization}/plugin-packs/`;

export function useUploadPack(organization: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: FormData) => apiFetch<components["schemas"]["TenantPackInstalled"]>(
      `/cms/organizations/${organization}/packs/`, { method: "POST", body },
    ),
    onSuccess: () => client.invalidateQueries({ queryKey: key(organization) }),
  });
}

export function useAdapterPacks(organization: string, page: number) {
  return useQuery({
    queryKey: [...key(organization), "page", page],
    queryFn: ({ signal }) => apiFetch<components["schemas"]["PaginatedRuntimePluginPackList"]>(`${base(organization)}?page=${page}`, { signal }),
  });
}

export function useAdapterPackDetail(organization: string, pack: string) {
  return useQuery({
    queryKey: [...key(organization), "detail", pack], enabled: Boolean(pack),
    queryFn: ({ signal }) => apiFetch<AdapterPackDetail>(`${base(organization)}${encodeURIComponent(pack)}/`, { signal }),
  });
}

export function useBindAdapterPack(organization: string, pack: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: AdapterPackUpdate) => apiFetch(`${base(organization)}${encodeURIComponent(pack)}/`, { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: key(organization) }),
  });
}
