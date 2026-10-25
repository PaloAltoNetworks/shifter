/** TanStack Query bindings for scoped authorization administration (#2315). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiFetch } from "./client";
import { isApiError } from "./errors";
import type {
  AuthorizationAction,
  AuthorizationEffect,
  AuthorizationMetadata,
  AuthorizationMutation,
  AuthorizationOperation,
  PredefinedAuthorizationPolicy,
} from "./types";

export type AuthorizationScope = string | Readonly<{
  kind: "installation" | "account" | "organization" | "workspace";
  uuid?: string;
  accountUuid?: string;
}>;

export const authorizationKeys = {
  all: ["authorization"] as const,
  catalog: () => ["authorization", "catalog"] as const,
  predefinedCatalog: () => ["authorization", "predefined-catalog"] as const,
  groups: (workspaceUuid: AuthorizationScope) => ["authorization", workspaceUuid, "groups"] as const,
  policies: (workspaceUuid: AuthorizationScope) => ["authorization", workspaceUuid, "policies"] as const,
  operation: (workspaceUuid: AuthorizationScope, operationUuid: string) =>
    ["authorization", workspaceUuid, "operations", operationUuid] as const,
};

const workspacePath = (scope: AuthorizationScope) => {
  if (typeof scope === "string") return `/workspaces/${encodeURIComponent(scope)}/authorization`;
  const uuid = encodeURIComponent(scope.uuid ?? "");
  if (scope.kind === "installation") return "/administer/authorization";
  if (scope.kind === "account") return `/accounts/${uuid}/authorization`;
  if (scope.kind === "organization") return `/accounts/${encodeURIComponent(scope.accountUuid ?? "")}/organizations/${uuid}/authorization`;
  return `/workspaces/${uuid}/authorization`;
};

const operationPath = (scope: AuthorizationScope, uuid: string) => {
  // Root organizer commands have a concrete organization UUID. The owning
  // recovery service derives its account ancestry without a client guess.
  const prefix = typeof scope !== "string" && scope.kind === "organization" && !scope.accountUuid
    ? `/organizations/${encodeURIComponent(scope.uuid ?? "")}/authorization`
    : workspacePath(scope);
  return `${prefix}/operations/${encodeURIComponent(uuid)}/`;
};

export function useAuthorizationCatalog() {
  return useQuery({
    queryKey: authorizationKeys.catalog(),
    queryFn: ({ signal }) => apiFetch<AuthorizationAction[]>("/workspaces/authorization/catalog/", { signal }),
  });
}

export function usePredefinedAuthorizationCatalog() {
  return useQuery({
    queryKey: authorizationKeys.predefinedCatalog(),
    queryFn: ({ signal }) =>
      apiFetch<PredefinedAuthorizationPolicy[]>("/workspaces/authorization/predefined-catalog/", { signal }),
  });
}

export function useAuthorizationGroups(workspaceUuid: AuthorizationScope) {
  return useQuery({
    queryKey: authorizationKeys.groups(workspaceUuid),
    enabled: Boolean(workspaceUuid),
    queryFn: ({ signal }) =>
      apiFetch<AuthorizationMetadata[]>(`${workspacePath(workspaceUuid)}/groups/`, { signal }),
  });
}

export function useAuthorizationPolicies(workspaceUuid: AuthorizationScope) {
  return useQuery({
    queryKey: authorizationKeys.policies(workspaceUuid),
    enabled: Boolean(workspaceUuid),
    queryFn: ({ signal }) =>
      apiFetch<AuthorizationMetadata[]>(`${workspacePath(workspaceUuid)}/policies/`, { signal }),
  });
}

function useCreateMetadata(workspaceUuid: AuthorizationScope, kind: "groups" | "policies") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description?: string }) =>
      apiFetch<AuthorizationMetadata>(`${workspacePath(workspaceUuid)}/${kind}/`, { method: "POST", body }),
    retry: false,
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey:
          kind === "groups"
            ? authorizationKeys.groups(workspaceUuid)
            : authorizationKeys.policies(workspaceUuid),
      }),
  });
}

export const useCreateAuthorizationGroup = (workspaceUuid: AuthorizationScope) =>
  useCreateMetadata(workspaceUuid, "groups");
export const useCreateAuthorizationPolicy = (workspaceUuid: AuthorizationScope) =>
  useCreateMetadata(workspaceUuid, "policies");

interface MutationBase {
  effect: AuthorizationEffect;
}

export function useRelationshipMutation<T>(path: string) {
  const [recovering, setRecovering] = useState(false);
  const mutation = useMutation({
    mutationFn: (command: { path: string; body: T & { idempotency_key: string } }) =>
      apiFetch<AuthorizationMutation>(command.path, { method: "POST", body: command.body }),
    retry: false,
  });
  // Transport/5xx failures may follow a committed write. Only known admission
  // failures allow editing; an uncertain command retains both its URL and body.
  const rejected = isApiError(mutation.error) && [400, 401, 403, 404, 405, 422].includes(mutation.error.status);
  const uncertain = mutation.isError && (recovering || !rejected);
  return {
    ...mutation,
    uncertain,
    mutate: (body: T) => {
      if (mutation.isPending || uncertain) return;
      setRecovering(false);
      mutation.mutate({ path, body: { ...body, idempotency_key: crypto.randomUUID() } });
    },
    retryCommand: () => {
      if (uncertain && mutation.variables) {
        setRecovering(true);
        mutation.mutate(mutation.variables);
      }
    },
  };
}

export function useGroupMembership(workspaceUuid: AuthorizationScope, groupUuid: string) {
  return useRelationshipMutation<MutationBase & { principal_uuid: string }>(
    `${workspacePath(workspaceUuid)}/groups/${groupUuid}/memberships/`,
  );
}

export function usePolicyAssignment(workspaceUuid: AuthorizationScope, policyUuid: string) {
  return useRelationshipMutation<MutationBase & { subject_kind: "principal" | "group"; subject_uuid: string }>(
    `${workspacePath(workspaceUuid)}/policies/${policyUuid}/assignments/`,
  );
}

export function usePolicyAction(workspaceUuid: AuthorizationScope, policyUuid: string) {
  return useRelationshipMutation<MutationBase & { action: string }>(
    `${workspacePath(workspaceUuid)}/policies/${policyUuid}/actions/`,
  );
}

export function useDirectAssignment(workspaceUuid: AuthorizationScope) {
  return useRelationshipMutation<MutationBase & { action: string; subject_kind: "principal" | "group"; subject_uuid: string }>(
    `${workspacePath(workspaceUuid)}/direct-assignments/`,
  );
}

export function usePredefinedAssignment(workspaceUuid: AuthorizationScope) {
  return useRelationshipMutation<MutationBase & { policy_code: string; subject_kind: "principal" | "group"; subject_uuid: string }>(
    `${workspacePath(workspaceUuid)}/predefined-assignments/`,
  );
}

export function useAuthorizationOperation(
  workspaceUuid: AuthorizationScope,
  operationUuid: string,
  enabled = true,
) {
  return useQuery({
    queryKey: authorizationKeys.operation(workspaceUuid, operationUuid),
    enabled: enabled && Boolean(workspaceUuid) && Boolean(operationUuid),
    queryFn: ({ signal }) =>
      apiFetch<AuthorizationOperation>(
        operationPath(workspaceUuid, operationUuid),
        { signal },
      ),
    retry: false,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      const pending = state === "requested" || state === "unresolved";
      return pending && query.state.dataUpdateCount < 10 ? 1000 : false;
    },
  });
}

export function useReconcileAuthorizationOperation(workspaceUuid: AuthorizationScope, operationUuid: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<AuthorizationOperation>(
        operationPath(workspaceUuid, operationUuid),
        { method: "POST", body: {} },
      ),
    retry: false,
    onSuccess: async (operation) => {
      const queryKey = authorizationKeys.operation(workspaceUuid, operationUuid);
      await queryClient.cancelQueries({ queryKey });
      queryClient.setQueryData(queryKey, operation);
    },
  });
}
