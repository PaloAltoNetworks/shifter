/**
 * Organizer operations hooks split from ctfAdmin.ts (file-size gate): event
 * lifecycle and scheduler controls, staff, challenge-pack transfer, results
 * export, and webhooks. Import via "@/api/ctfAdmin" (re-exported) or here.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import { ctfKeys } from "./ctf";
import type {
  CtfEventAnalytics,
  CtfEventPage,
  CtfEventPagesResponse,
  CtfEventPageWrite,
  CtfNotificationAnnounceRequest,
  CtfNotificationListResponse,
  CtfNotificationSendResult,
  CtfChallengeImportResult,
  CtfCleanupControlRequest,
  CtfEventLifecycleAction,
  CtfEventMutationResult,
  CtfEventStaffAssignRequest,
  CtfEventStaffListResponse,
  CtfEventStaffMember,
  CtfScheduledTask,
  CtfScheduledTaskListResponse,
  CtfWebhook,
  CtfWebhookListResponse,
  CtfWebhookWrite,
} from "./types";

const BASE = "/ctf";

// --- Event lifecycle + scheduler controls (CTF-007, #526, CTF-1003) -------

export function useCtfEventLifecycle(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (action: CtfEventLifecycleAction) =>
      apiFetch<CtfEventMutationResult>(`${BASE}/events/${eventId}/lifecycle/`, { method: "POST", body: { action } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ctfKeys.event(eventId) });
      queryClient.invalidateQueries({ queryKey: ctfKeys.events() });
      queryClient.invalidateQueries({ queryKey: ctfKeys.eventTasks(eventId) });
    },
  });
}

export function useCtfEventTasks(eventId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.eventTasks(eventId),
    enabled: enabled && Boolean(eventId),
    queryFn: ({ signal }) => apiFetch<CtfScheduledTaskListResponse>(`${BASE}/events/${eventId}/tasks/`, { signal }),
  });
}

export function useRunCtfTaskNow(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) =>
      apiFetch<CtfScheduledTask>(`${BASE}/events/${eventId}/tasks/${taskId}/run/`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.eventTasks(eventId) }),
  });
}

export function useCtfCleanupControl(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CtfCleanupControlRequest) =>
      apiFetch<CtfScheduledTaskListResponse>(`${BASE}/events/${eventId}/cleanup/`, { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.eventTasks(eventId) }),
  });
}

// --- Event staff (CTF-607) ------------------------------------------------

export function useCtfEventStaff(eventId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.eventStaff(eventId),
    enabled: enabled && Boolean(eventId),
    queryFn: ({ signal }) => apiFetch<CtfEventStaffListResponse>(`${BASE}/events/${eventId}/staff/`, { signal }),
  });
}

export function useAssignCtfEventStaff(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CtfEventStaffAssignRequest) =>
      apiFetch<CtfEventStaffMember>(`${BASE}/events/${eventId}/staff/`, { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.eventStaff(eventId) }),
  });
}

export function useRevokeCtfEventStaff(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: number) =>
      apiFetch<unknown>(`${BASE}/events/${eventId}/staff/${userId}/`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.eventStaff(eventId) }),
  });
}

// --- Notifications --------------------------------------------------------

export function useCtfNotifications(eventId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.notifications(eventId),
    enabled: enabled && Boolean(eventId),
    queryFn: ({ signal }) =>
      apiFetch<CtfNotificationListResponse>(`${BASE}/events/${eventId}/notifications/`, { signal }),
  });
}

export function useAnnounceCtfNotification(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CtfNotificationAnnounceRequest) =>
      apiFetch<unknown>(`${BASE}/events/${eventId}/notifications/`, { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.notifications(eventId) }),
  });
}

export function useSendCtfNotification(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (notificationId: string) =>
      apiFetch<CtfNotificationSendResult>(`${BASE}/notifications/${notificationId}/send/`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.notifications(eventId) }),
  });
}

export function useCancelCtfScheduledNotification(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (notificationId: string) =>
      apiFetch<unknown>(`${BASE}/notifications/${notificationId}/cancel-schedule/`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.notifications(eventId) }),
  });
}

// --- Analytics + custom pages (CTF-1302/1303) -----------------------------

export function useCtfEventAnalytics(eventId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.analytics(eventId),
    enabled: enabled && Boolean(eventId),
    queryFn: ({ signal }) =>
      apiFetch<CtfEventAnalytics>(`${BASE}/events/${eventId}/analytics/`, { signal }),
  });
}

export function useCtfEventPages(eventId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.eventPages(eventId),
    enabled: enabled && Boolean(eventId),
    queryFn: ({ signal }) => apiFetch<CtfEventPagesResponse>(`${BASE}/events/${eventId}/pages/`, { signal }),
  });
}

export function useCreateCtfEventPage(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CtfEventPageWrite) =>
      apiFetch<CtfEventPage>(`${BASE}/events/${eventId}/pages/`, { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.eventPages(eventId) }),
  });
}

export function useUpdateCtfEventPage(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ pageId, ...body }: Partial<CtfEventPageWrite> & { pageId: string }) =>
      apiFetch<CtfEventPage>(`${BASE}/pages/${pageId}/`, { method: "PUT", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.eventPages(eventId) }),
  });
}

export function useDeleteCtfEventPage(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (pageId: string) => apiFetch<unknown>(`${BASE}/pages/${pageId}/`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.eventPages(eventId) }),
  });
}

// --- Import/export + webhooks (CTF-1101..1104, CTF-1203) -------------------

export function exportCtfChallenges(eventId: string, fmt: "shifter" | "ctfd") {
  return apiFetch<Record<string, unknown>>(`${BASE}/events/${eventId}/challenges/export/?fmt=${fmt}`);
}

export function useImportCtfChallenges(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      apiFetch<CtfChallengeImportResult>(`${BASE}/events/${eventId}/challenges/import-pack/`, {
        method: "POST",
        body: { payload },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.adminChallenges(eventId) }),
  });
}

export function exportCtfResults(eventId: string) {
  return apiFetch<Record<string, unknown>>(`${BASE}/events/${eventId}/results/export/`);
}

export function useCtfWebhooks(eventId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.webhooks(eventId),
    enabled: enabled && Boolean(eventId),
    queryFn: ({ signal }) => apiFetch<CtfWebhookListResponse>(`${BASE}/events/${eventId}/webhooks/`, { signal }),
  });
}

export function useCreateCtfWebhook(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CtfWebhookWrite) =>
      apiFetch<CtfWebhook>(`${BASE}/events/${eventId}/webhooks/`, { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.webhooks(eventId) }),
  });
}

export function useDeleteCtfWebhook(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (webhookId: string) => apiFetch<unknown>(`${BASE}/webhooks/${webhookId}/`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.webhooks(eventId) }),
  });
}
