/** TanStack Query hooks for the staff-session-only workspace invitation API. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type { IssueWorkspaceInvitationRequest, WorkspaceInvitation } from "./types";

export const invitationKeys = {
  all: ["workspaces", "invitations"] as const,
  list: (uuid: string) => ["workspaces", "invitations", uuid] as const,
};

function invalidate(queryClient: ReturnType<typeof useQueryClient>, uuid: string) {
  queryClient.invalidateQueries({ queryKey: invitationKeys.list(uuid) });
}

export function useWorkspaceInvitations(uuid: string, enabled = true) {
  return useQuery({
    queryKey: invitationKeys.list(uuid),
    enabled: enabled && Boolean(uuid),
    queryFn: ({ signal }) => apiFetch<WorkspaceInvitation[]>(`/workspaces/${uuid}/invitations/`, { signal }),
  });
}

export function useIssueWorkspaceInvitation(uuid: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: IssueWorkspaceInvitationRequest) =>
      apiFetch<WorkspaceInvitation>(`/workspaces/${uuid}/invitations/`, { method: "POST", body }),
    onSuccess: () => invalidate(queryClient, uuid),
  });
}

export function useResendWorkspaceInvitation(uuid: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (invitationUuid: string) =>
      apiFetch<WorkspaceInvitation>(`/workspaces/${uuid}/invitations/${invitationUuid}/resend/`, { method: "POST" }),
    onSuccess: () => invalidate(queryClient, uuid),
  });
}

export function useRevokeWorkspaceInvitation(uuid: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (invitationUuid: string) =>
      apiFetch<WorkspaceInvitation>(`/workspaces/${uuid}/invitations/${invitationUuid}/revoke/`, { method: "POST" }),
    onSuccess: () => invalidate(queryClient, uuid),
  });
}
