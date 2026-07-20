/**
 * TanStack Query hooks for the CTF organizer (admin) workspace API surface
 * (#1372). Split from `ctf.ts` so each file stays within the size budget.
 *
 * The organizer workspace mutates through the same canonical `/api/v1/ctf/`
 * routes; caching, invalidation, and retry policy live here. Reads use the
 * organizer key namespaces declared on `ctfKeys`; mutations invalidate the
 * affected list/detail reads. All calls go through the shared typed `apiFetch`
 * client.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import { ctfKeys } from "./ctf";
import type {
  CtfAssignBracketResult,
  CtfAward,
  CtfAwardListResponse,
  CtfChallengeFileListResponse,
  CtfChallengeFileUploadResult,
  CtfChallengeListResponse,
  CtfChallengeMutationResult,
  CtfChallengeWrite,
  CtfEventDetail,
  CtfEventListResponse,
  CtfEventMutationResult,
  CtfEventWrite,
  CtfFlagCreateResult,
  CtfFlagWrite,
  CtfForceDeleteEventResult,
  CtfHintListResponse,
  CtfHintWrite,
  CtfOrganizerChallengeDetail,
  CtfOrganizerParticipantDetail,
  CtfParticipantImportResult,
  CtfParticipantInvite,
  CtfParticipantListResponse,
  CtfParticipantRangeActionResult,
  CtfPrerequisiteListResponse,
  CtfPrerequisiteWrite,
  CtfRangeListResponse,
  CtfRangeProvisionQueued,
  CtfScenarioListResponse,
  CtfScoreTimelineResponse,
} from "./types";

const BASE = "/ctf";

// --- Events ---------------------------------------------------------------

export function useCtfEvents() {
  return useQuery({
    queryKey: ctfKeys.events(),
    queryFn: ({ signal }) => apiFetch<CtfEventListResponse>(`${BASE}/events/`, { signal }),
  });
}

export function useCtfEvent(eventId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.event(eventId),
    enabled: enabled && Boolean(eventId),
    queryFn: ({ signal }) => apiFetch<CtfEventDetail>(`${BASE}/events/${eventId}/`, { signal }),
  });
}

export function useCtfScenarios(enabled = true) {
  return useQuery({
    queryKey: ctfKeys.scenarios(),
    enabled,
    queryFn: ({ signal }) => apiFetch<CtfScenarioListResponse>(`${BASE}/scenarios/`, { signal }),
  });
}

export function useCreateCtfEvent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CtfEventWrite) =>
      apiFetch<CtfEventMutationResult>(`${BASE}/events/`, { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.events() }),
  });
}

export function useUpdateCtfEvent(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CtfEventWrite) =>
      apiFetch<CtfEventMutationResult>(`${BASE}/events/${eventId}/`, { method: "PUT", body }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ctfKeys.event(eventId) });
      queryClient.invalidateQueries({ queryKey: ctfKeys.events() });
    },
  });
}

export function useDeleteCtfEvent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (eventId: string) => apiFetch<void>(`${BASE}/events/${eventId}/`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.events() }),
  });
}

export function useForceDeleteCtfEvent(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (confirmationName: string) =>
      apiFetch<CtfForceDeleteEventResult>(`${BASE}/events/${eventId}/force-delete/`, {
        method: "POST",
        body: { confirmation_name: confirmationName },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.events() }),
  });
}

// --- Challenges -----------------------------------------------------------

export function useCtfEventChallenges(eventId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.adminChallenges(eventId),
    enabled: enabled && Boolean(eventId),
    queryFn: ({ signal }) =>
      apiFetch<CtfChallengeListResponse>(`${BASE}/events/${eventId}/challenges/`, { signal }),
  });
}

export function useCtfOrganizerChallenge(challengeId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.adminChallenge(challengeId),
    enabled: enabled && Boolean(challengeId),
    queryFn: ({ signal }) =>
      apiFetch<CtfOrganizerChallengeDetail>(`${BASE}/challenges/${challengeId}/`, { signal }),
  });
}

export function useCreateCtfChallenge(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CtfChallengeWrite) =>
      apiFetch<CtfChallengeMutationResult>(`${BASE}/events/${eventId}/challenges/`, { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.adminChallenges(eventId) }),
  });
}

export function useUpdateCtfChallenge(challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CtfChallengeWrite) =>
      apiFetch<CtfChallengeMutationResult>(`${BASE}/challenges/${challengeId}/`, { method: "PUT", body }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ctfKeys.adminChallenge(challengeId) });
      queryClient.invalidateQueries({ queryKey: ctfKeys.adminChallengesAll() });
    },
  });
}

export function useDeleteCtfChallenge() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (challengeId: string) =>
      apiFetch<void>(`${BASE}/challenges/${challengeId}/`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.adminChallengesAll() }),
  });
}

// --- Flags (write-only from the organizer UI) -----------------------------

export function useAddCtfFlag(challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CtfFlagWrite) =>
      apiFetch<CtfFlagCreateResult>(`${BASE}/challenges/${challengeId}/flags/add/`, { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.adminChallenge(challengeId) }),
  });
}

export function useRemoveCtfFlag(challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (flagId: string) => apiFetch<void>(`${BASE}/flags/${flagId}/remove/`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.adminChallenge(challengeId) }),
  });
}

// --- Hints ----------------------------------------------------------------

export function useCtfChallengeHints(challengeId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.hints(challengeId),
    enabled: enabled && Boolean(challengeId),
    queryFn: ({ signal }) => apiFetch<CtfHintListResponse>(`${BASE}/challenges/${challengeId}/hints/`, { signal }),
  });
}

export function useAddCtfHint(challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CtfHintWrite) =>
      apiFetch<CtfHintListResponse>(`${BASE}/challenges/${challengeId}/hints/`, { method: "POST", body }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ctfKeys.hints(challengeId) });
      queryClient.invalidateQueries({ queryKey: ctfKeys.adminChallenge(challengeId) });
    },
  });
}

export function useDeleteCtfHint(challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (hintId: string) => apiFetch<void>(`${BASE}/hints/${hintId}/delete/`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ctfKeys.hints(challengeId) });
      queryClient.invalidateQueries({ queryKey: ctfKeys.adminChallenge(challengeId) });
    },
  });
}

// --- Files ----------------------------------------------------------------

export function useCtfChallengeFiles(challengeId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.files(challengeId),
    enabled: enabled && Boolean(challengeId),
    queryFn: ({ signal }) =>
      apiFetch<CtfChallengeFileListResponse>(`${BASE}/challenges/${challengeId}/files/`, { signal }),
  });
}

export function useUploadCtfChallengeFile(challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, displayName }: { file: File; displayName?: string }) => {
      const form = new FormData();
      form.append("file", file);
      if (displayName) form.append("display_name", displayName);
      return apiFetch<CtfChallengeFileUploadResult>(`${BASE}/challenges/${challengeId}/files/`, {
        method: "POST",
        body: form,
      });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.files(challengeId) }),
  });
}

export function useDeleteCtfChallengeFile(challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (fileId: string) => apiFetch<void>(`${BASE}/files/${fileId}/delete/`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.files(challengeId) }),
  });
}

// --- Prerequisites --------------------------------------------------------

export function useCtfChallengePrerequisites(challengeId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.prerequisites(challengeId),
    enabled: enabled && Boolean(challengeId),
    queryFn: ({ signal }) =>
      apiFetch<CtfPrerequisiteListResponse>(`${BASE}/challenges/${challengeId}/prerequisites/`, { signal }),
  });
}

export function useAddCtfPrerequisite(challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CtfPrerequisiteWrite) =>
      apiFetch<CtfPrerequisiteListResponse>(`${BASE}/challenges/${challengeId}/prerequisites/`, {
        method: "POST",
        body,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.prerequisites(challengeId) }),
  });
}

export function useDeleteCtfPrerequisite(challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (prerequisiteId: string) =>
      apiFetch<void>(`${BASE}/prerequisites/${prerequisiteId}/delete/`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.prerequisites(challengeId) }),
  });
}

// --- Participants ---------------------------------------------------------

export function useCtfParticipants(eventId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.participants(eventId),
    enabled: enabled && Boolean(eventId),
    queryFn: ({ signal }) =>
      apiFetch<CtfParticipantListResponse>(`${BASE}/events/${eventId}/participants/`, { signal }),
  });
}

export function useCtfParticipant(participantId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.participant(participantId),
    enabled: enabled && Boolean(participantId),
    queryFn: ({ signal }) =>
      apiFetch<CtfOrganizerParticipantDetail>(`${BASE}/participants/${participantId}/`, { signal }),
  });
}

export function useInviteCtfParticipant(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CtfParticipantInvite) =>
      apiFetch<unknown>(`${BASE}/events/${eventId}/participants/`, { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.participants(eventId) }),
  });
}

export function useImportCtfParticipants(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (participants: unknown[]) =>
      apiFetch<CtfParticipantImportResult>(`${BASE}/events/${eventId}/participants/import/`, {
        method: "POST",
        body: { participants },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.participants(eventId) }),
  });
}

export function useCtfParticipantAwards(participantId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.awards(participantId),
    enabled: enabled && Boolean(participantId),
    queryFn: ({ signal }) =>
      apiFetch<CtfAwardListResponse>(`${BASE}/participants/${participantId}/awards/`, { signal }),
  });
}

export function useGrantCtfAward(participantId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { points: number; reason: string }) =>
      apiFetch<CtfAward>(`${BASE}/participants/${participantId}/awards/`, { method: "POST", body }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ctfKeys.awards(participantId) });
      queryClient.invalidateQueries({ queryKey: ctfKeys.participant(participantId) });
    },
  });
}

export function useRevokeCtfAward(participantId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (awardId: string) => apiFetch<void>(`${BASE}/awards/${awardId}/delete/`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ctfKeys.awards(participantId) });
      queryClient.invalidateQueries({ queryKey: ctfKeys.participant(participantId) });
    },
  });
}

export function useResendCtfInvite(participantId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<unknown>(`${BASE}/participants/${participantId}/resend-invite/`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.participant(participantId) }),
  });
}

export function useAssignCtfBracket(participantId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (bracketId: string | null) =>
      apiFetch<CtfAssignBracketResult>(`${BASE}/participants/${participantId}/bracket/`, {
        method: "POST",
        body: { bracket_id: bracketId },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.participant(participantId) }),
  });
}

function useParticipantAction<TBody = Record<string, never>>(participantId: string, path: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TBody) =>
      apiFetch<CtfOrganizerParticipantDetail>(`${BASE}/participants/${participantId}/${path}/`, {
        method: "POST",
        body,
      }),
    onSuccess: (detail) => {
      queryClient.invalidateQueries({ queryKey: ctfKeys.participant(participantId) });
      queryClient.invalidateQueries({ queryKey: ctfKeys.participants(detail.event_id) });
    },
  });
}

export function useBanCtfParticipant(participantId: string) {
  return useParticipantAction<{ reason?: string }>(participantId, "ban");
}

export function useUnbanCtfParticipant(participantId: string) {
  return useParticipantAction(participantId, "unban");
}

export function useDisqualifyCtfParticipant(participantId: string) {
  return useParticipantAction<{ reason?: string }>(participantId, "disqualify");
}

export function useRequalifyCtfParticipant(participantId: string) {
  return useParticipantAction(participantId, "requalify");
}

export function useSetCtfParticipantRole(participantId: string) {
  return useParticipantAction<{ role: string }>(participantId, "role");
}

export function useSetCtfParticipantHidden(participantId: string) {
  return useParticipantAction<{ hidden: boolean }>(participantId, "hidden");
}

export function useRenameCtfParticipant(participantId: string) {
  return useParticipantAction<{ username: string }>(participantId, "username");
}

// --- Ranges ---------------------------------------------------------------

export function useCtfEventRanges(eventId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.ranges(eventId),
    enabled: enabled && Boolean(eventId),
    queryFn: ({ signal }) => apiFetch<CtfRangeListResponse>(`${BASE}/events/${eventId}/ranges/`, { signal }),
  });
}

export function useProvisionCtfEventRanges(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<CtfRangeProvisionQueued>(`${BASE}/events/${eventId}/ranges/provision/`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.ranges(eventId) }),
  });
}

export function useProvisionCtfEventSpares(eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (count: number) =>
      apiFetch<unknown>(`${BASE}/events/${eventId}/spares/`, { method: "POST", body: { count } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.ranges(eventId) }),
  });
}

/** Participant range lifecycle action (provision/destroy/stop/start/restart). */
export type CtfRangeAction = "provision" | "destroy" | "stop" | "start" | "restart";

export function useCtfParticipantRangeAction(participantId: string, eventId?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (action: CtfRangeAction) =>
      apiFetch<CtfParticipantRangeActionResult>(`${BASE}/participants/${participantId}/range/${action}/`, {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ctfKeys.participant(participantId) });
      if (eventId) queryClient.invalidateQueries({ queryKey: ctfKeys.ranges(eventId) });
    },
  });
}

// --- Score timeline (analytics) -------------------------------------------

export function useCtfScoreTimeline(participantId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.scoreTimeline(participantId),
    enabled: enabled && Boolean(participantId),
    queryFn: ({ signal }) =>
      apiFetch<CtfScoreTimelineResponse>(`${BASE}/participants/${participantId}/score-timeline/`, { signal }),
  });
}

export * from "./ctfAdminOps";
