/** Dormant S4 clients; DRF's prepared contract remains the type source. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch, type QueryValue } from "./client";
import type { components } from "./account-admin-schema";

export type AdministrationSchemas = components["schemas"];
export type Account = AdministrationSchemas["AccountView"];
export type Organization = AdministrationSchemas["OrganizationView"];
export type Workspace = AdministrationSchemas["WorkspaceView"];
export type MembershipPage = AdministrationSchemas["AccountMemberPage"];
export type Scope = Readonly<{ kind: "account" | "organization" | "workspace"; uuid: string }>;

const scopeCollections = { account: "accounts", organization: "organizations", workspace: "workspaces" } as const;
export const scopePath = (scope: Scope) => `/${scopeCollections[scope.kind]}/${encodeURIComponent(scope.uuid)}`;

export function useAdministrationQuery<T>(path: string, query?: Record<string, QueryValue>, enabled = true) {
  return useQuery({
    queryKey: ["account-administration", path, query],
    enabled: enabled && Boolean(path),
    queryFn: ({ signal }) => apiFetch<T>(path, { query, signal }),
  });
}

export function useAdministrationMutation<T = unknown, B = unknown>(path: string, method = "POST") {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: B) => apiFetch<T>(path, { method, body }),
    retry: false,
    onSuccess: () => client.invalidateQueries({ queryKey: ["account-administration"] }),
  });
}
