/**
 * TanStack Query hooks for the CTF participant workspace API surface (#1372).
 * All caching, invalidation, and retry policy live here; components call these
 * hooks and never fetch directly. The SPA uses the canonical `/api/v1/ctf/` DRF
 * routes only — it never touches the legacy `/ctf/` Django page/form URLs.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiDownload, apiFetch } from "./client";
import { ApiError } from "./errors";
import type {
  CtfAnnouncementListResponse,
  CtfChallengeDetail,
  CtfChallengeListItem,
  CtfCurrentEvent,
  CtfOrganizerScoreboard,
  CtfParticipantProfile,
  CtfProfileUpdateRequest,
  CtfRangeAccess,
  CtfRangeStatus,
  CtfRateChallengeResult,
  CtfScoreboard,
  CtfSubmissionList,
  CtfSubmitFlagResult,
  CtfTeam,
  CtfUseHintResult,
} from "./types";

const BASE = "/ctf";

/** Query-key segment for the organizer challenge lists (shared by the read key and its invalidations). */
const ADMIN_CHALLENGES_KEY = "admin-challenges";

export const ctfKeys = {
  all: ["ctf"] as const,
  currentEvent: () => ["ctf", "current-event"] as const,
  challenges: () => ["ctf", "challenges"] as const,
  challenge: (id: string) => ["ctf", "challenge", id] as const,
  team: () => ["ctf", "team"] as const,
  profile: () => ["ctf", "profile"] as const,
  announcements: () => ["ctf", "announcements"] as const,
  submissions: () => ["ctf", "submissions"] as const,
  rangeStatus: () => ["ctf", "range-status"] as const,
  scoreboard: (eventId: string, bracketId?: string) => ["ctf", "scoreboard", eventId, bracketId ?? null] as const,
  organizerScoreboard: (eventId: string, bracketId?: string) =>
    ["ctf", "organizer-scoreboard", eventId, bracketId ?? null] as const,
  // Organizer read keys (distinct namespaces from the participant reads above).
  events: () => ["ctf", "events"] as const,
  event: (id: string) => ["ctf", "event", id] as const,
  scenarios: () => ["ctf", "scenarios"] as const,
  adminChallenges: (eventId: string) => ["ctf", ADMIN_CHALLENGES_KEY, eventId] as const,
  adminChallengesAll: () => ["ctf", ADMIN_CHALLENGES_KEY] as const,
  adminChallenge: (id: string) => ["ctf", "admin-challenge", id] as const,
  hints: (challengeId: string) => ["ctf", "hints", challengeId] as const,
  files: (challengeId: string) => ["ctf", "files", challengeId] as const,
  prerequisites: (challengeId: string) => ["ctf", "prerequisites", challengeId] as const,
  participants: (eventId: string) => ["ctf", "participants", eventId] as const,
  participant: (id: string) => ["ctf", "participant", id] as const,
  awards: (participantId: string) => ["ctf", "awards", participantId] as const,
  ranges: (eventId: string) => ["ctf", "ranges", eventId] as const,
  notifications: (eventId: string) => ["ctf", "notifications", eventId] as const,
  scoreTimeline: (participantId: string) => ["ctf", "score-timeline", participantId] as const,
  eventStaff: (eventId: string) => ["ctf", "event-staff", eventId] as const,
  eventTasks: (eventId: string) => ["ctf", "event-tasks", eventId] as const,
  webhooks: (eventId: string) => ["ctf", "webhooks", eventId] as const,
};

export function useCtfCurrentEvent() {
  return useQuery({
    queryKey: ctfKeys.currentEvent(),
    queryFn: ({ signal }) => apiFetch<CtfCurrentEvent>(`${BASE}/me/event/`, { signal }),
  });
}

export function useCtfChallenges() {
  return useQuery({
    queryKey: ctfKeys.challenges(),
    queryFn: ({ signal }) => apiFetch<CtfChallengeListItem[]>(`${BASE}/me/challenges/`, { signal }),
  });
}

export function useCtfChallenge(challengeId: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.challenge(challengeId),
    enabled: enabled && Boolean(challengeId),
    queryFn: ({ signal }) => apiFetch<CtfChallengeDetail>(`${BASE}/me/challenges/${challengeId}/`, { signal }),
  });
}

export function useCtfTeam() {
  return useQuery({
    queryKey: ctfKeys.team(),
    // A 404 is the server's ordinary "not on a team" answer (solo events /
    // unassigned), so it resolves to null rather than an error state.
    queryFn: async ({ signal }): Promise<CtfTeam | null> => {
      try {
        return await apiFetch<CtfTeam>(`${BASE}/me/team/`, { signal });
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
  });
}

export function useCtfSubmissions() {
  return useQuery({
    queryKey: ctfKeys.submissions(),
    queryFn: ({ signal }) => apiFetch<CtfSubmissionList>(`${BASE}/submissions/`, { signal }),
  });
}

export function useCtfRangeStatus() {
  return useQuery({
    queryKey: ctfKeys.rangeStatus(),
    queryFn: ({ signal }) => apiFetch<CtfRangeStatus>(`${BASE}/range/status/`, { signal }),
  });
}

export function useCtfScoreboard(eventId: string, bracketId?: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.scoreboard(eventId, bracketId),
    enabled: enabled && Boolean(eventId),
    queryFn: ({ signal }) =>
      apiFetch<CtfScoreboard>(`${BASE}/events/${eventId}/scoreboard/`, {
        signal,
        query: bracketId ? { bracket: bracketId } : undefined,
      }),
  });
}

/**
 * Organizer monitoring scoreboard. Unlike {@link useCtfScoreboard} (the public,
 * participant-facing read that honors `scoreboard_visible`/freeze and returns the
 * `scoreboard_hidden` sentinel), this hits the organizer-authenticated endpoint
 * that always returns the full ranking payload regardless of visibility/freeze.
 * Use it only from organizer surfaces; keep the participant scoreboard on the
 * public hook.
 */
export function useCtfOrganizerScoreboard(eventId: string, bracketId?: string, enabled = true) {
  return useQuery({
    queryKey: ctfKeys.organizerScoreboard(eventId, bracketId),
    enabled: enabled && Boolean(eventId),
    queryFn: ({ signal }) =>
      apiFetch<CtfOrganizerScoreboard>(`${BASE}/events/${eventId}/organizer-scoreboard/`, {
        signal,
        query: bracketId ? { bracket: bracketId } : undefined,
      }),
  });
}

/**
 * Invalidate the play-affecting reads after a submission or hint unlock: the
 * challenge detail (attempts/hints/solved), the browse list (solve status), the
 * current-event projection (score/rank), and the submission history.
 */
function invalidatePlay(queryClient: ReturnType<typeof useQueryClient>, challengeId: string) {
  queryClient.invalidateQueries({ queryKey: ctfKeys.challenge(challengeId) });
  queryClient.invalidateQueries({ queryKey: ctfKeys.challenges() });
  queryClient.invalidateQueries({ queryKey: ctfKeys.currentEvent() });
  queryClient.invalidateQueries({ queryKey: ctfKeys.submissions() });
}

export function useSubmitFlag(challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (flag: string) =>
      apiFetch<CtfSubmitFlagResult>(`${BASE}/challenges/${challengeId}/submit/`, {
        method: "POST",
        body: { flag },
      }),
    onSuccess: () => invalidatePlay(queryClient, challengeId),
  });
}

export function useUseHint(challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    // Omit `hint_id` to unlock the next hint in order, or pass one to unlock a
    // specific hint (mirrors the server's UseHintRequest contract).
    mutationFn: (hintId?: string) =>
      apiFetch<CtfUseHintResult>(`${BASE}/challenges/${challengeId}/hint/`, {
        method: "POST",
        body: hintId ? { hint_id: hintId } : {},
      }),
    onSuccess: () => invalidatePlay(queryClient, challengeId),
  });
}

function useTeamMutation<TBody>(path: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TBody) => apiFetch<CtfTeam>(`${BASE}/me/team/${path}/`, { method: "POST", body }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ctfKeys.team() });
      queryClient.invalidateQueries({ queryKey: ctfKeys.currentEvent() });
    },
  });
}

export function useCreateTeam() {
  return useTeamMutation<{ name: string }>("create");
}

export function useJoinTeam() {
  return useTeamMutation<{ invite_code: string }>("join");
}

export function useRenameTeam() {
  return useTeamMutation<{ name: string }>("rename");
}

export function useRegenerateTeamCode() {
  return useTeamMutation<Record<string, never>>("regenerate-code");
}

export function useTransferCaptaincy() {
  return useTeamMutation<{ participant_id: string }>("transfer-captaincy");
}

export function useRemoveTeamMember() {
  return useTeamMutation<{ participant_id: string }>("remove-member");
}

export function useLeaveTeam() {
  return useTeamMutation<Record<string, never>>("leave");
}

export function useDisbandTeam() {
  return useTeamMutation<Record<string, never>>("disband");
}

export function useCtfProfile() {
  return useQuery({
    queryKey: ctfKeys.profile(),
    queryFn: ({ signal }) => apiFetch<CtfParticipantProfile>(`${BASE}/me/profile/`, { signal }),
  });
}

export function useUpdateCtfProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CtfProfileUpdateRequest) =>
      apiFetch<CtfParticipantProfile>(`${BASE}/me/profile/`, { method: "PATCH", body }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ctfKeys.profile() });
      queryClient.invalidateQueries({ queryKey: ctfKeys.currentEvent() });
    },
  });
}

export function useChangeCtfUsername() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string }) =>
      apiFetch<CtfParticipantProfile>(`${BASE}/me/username/`, { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.profile() }),
  });
}

export function useCtfAnnouncements() {
  return useQuery({
    queryKey: ctfKeys.announcements(),
    queryFn: ({ signal }) => apiFetch<CtfAnnouncementListResponse>(`${BASE}/me/announcements/`, { signal }),
  });
}

export function useRateChallenge(challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (value: number) =>
      apiFetch<CtfRateChallengeResult>(`${BASE}/challenges/${challengeId}/rate/`, {
        method: "POST",
        body: { value },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.challenge(challengeId) }),
  });
}

export function useRangeAccess() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<CtfRangeAccess>(`${BASE}/range/access/`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ctfKeys.rangeStatus() }),
  });
}

const VPN_PROFILE_MEDIA_TYPE = "application/x-openvpn-profile";
const VPN_PROFILE_FILENAME = "shifter-ctf-range.ovpn";

export function useVpnProfileDownload() {
  return useMutation({
    mutationFn: async () => {
      const blob = await apiDownload(`${BASE}/range/vpn-profile/`, {
        method: "POST",
        expectedMediaType: VPN_PROFILE_MEDIA_TYPE,
        maxBytes: 64 * 1024,
      });
      const url = URL.createObjectURL(blob);
      try {
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = VPN_PROFILE_FILENAME;
        anchor.click();
      } finally {
        URL.revokeObjectURL(url);
      }
    },
  });
}

/**
 * Resolve a presigned download URL for a challenge attachment (used by the
 * imperative download action on the challenge detail page). The endpoint returns
 * a short-lived URL + filename rather than streaming the file, so the caller
 * fetches this then navigates to `url`.
 */
export function fetchCtfFileDownload(fileId: string): Promise<{ url: string; filename: string }> {
  return apiFetch<{ url: string; filename: string }>(`${BASE}/files/${fileId}/download/`);
}
