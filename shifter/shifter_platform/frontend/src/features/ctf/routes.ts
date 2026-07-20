/**
 * CTF participant workspace client-route paths (#1372).
 *
 * The CTF participant workspace still has a live legacy Django app at these same
 * paths (`ctf/urls.py`); every path builder here matches its page paths exactly,
 * trailing slash included, so a client-router deep link or refresh resolves the
 * same page the Django host would have served (the backend serves the SPA shell
 * for the wrapped participant page paths, and a scoped catch-all covers deeper
 * client sub-routes, once both SPA flags are on). Participant and organizer share
 * the `/ctf/` prefix, so these paths are not free to change shape independently
 * of the backend. Keeping the prefix in one place means a future re-mount changes
 * one file.
 */
export const CTF_BASE = "/ctf";

export const ctfEventHomePath = (): string => `${CTF_BASE}/`;
export const ctfEventPath = (): string => `${CTF_BASE}/event/`;
export const ctfChallengesPath = (): string => `${CTF_BASE}/challenges/`;
export const ctfChallengeDetailPath = (challengeId: string): string => `${CTF_BASE}/challenges/${challengeId}/`;
export const ctfRangePath = (): string => `${CTF_BASE}/range/`;
export const ctfScoreboardPath = (): string => `${CTF_BASE}/scoreboard/`;
export const ctfTeamPath = (): string => `${CTF_BASE}/team/`;
export const ctfAccountPath = (): string => `${CTF_BASE}/account/`;
export const ctfHelpPath = (): string => `${CTF_BASE}/help/`;

/**
 * Organizer (admin) client-route paths, under `/ctf/admin/`.
 *
 * These match the legacy Django organizer page paths (`ctf/urls.py`
 * ``admin_patterns``), trailing slash included, so a client-router deep link or
 * refresh resolves the same surface the Django host would have served. The
 * backend serves the SPA shell for the wrapped organizer GET page paths and a
 * scoped catch-all covers deeper organizer client sub-routes when both SPA flags
 * are on. The create/edit builders intentionally match the legacy Django form
 * URLs: those exact routes stay Django-served (for rollback), so a deep-link GET
 * lands on the classic form while in-SPA navigation renders the client form.
 */
export const CTF_ADMIN_BASE = `${CTF_BASE}/admin`;

export const ctfAdminDashboardPath = (): string => `${CTF_ADMIN_BASE}/`;
export const ctfAdminEventsPath = (): string => `${CTF_ADMIN_BASE}/events/`;
export const ctfAdminEventCreatePath = (): string => `${CTF_ADMIN_BASE}/events/create/`;
export const ctfAdminEventPath = (eventId: string): string => `${CTF_ADMIN_BASE}/events/${eventId}/`;
export const ctfAdminEventEditPath = (eventId: string): string => `${CTF_ADMIN_BASE}/events/${eventId}/edit/`;
export const ctfAdminEventChallengesPath = (eventId: string): string =>
  `${CTF_ADMIN_BASE}/events/${eventId}/challenges/`;
export const ctfAdminChallengeCreatePath = (eventId: string): string =>
  `${CTF_ADMIN_BASE}/events/${eventId}/challenges/create/`;
export const ctfAdminChallengePath = (challengeId: string): string => `${CTF_ADMIN_BASE}/challenges/${challengeId}/`;
export const ctfAdminChallengeEditPath = (challengeId: string): string =>
  `${CTF_ADMIN_BASE}/challenges/${challengeId}/edit/`;
export const ctfAdminEventParticipantsPath = (eventId: string): string =>
  `${CTF_ADMIN_BASE}/events/${eventId}/participants/`;
export const ctfAdminParticipantPath = (participantId: string): string =>
  `${CTF_ADMIN_BASE}/participants/${participantId}/`;
export const ctfAdminEventScoreboardPath = (eventId: string): string =>
  `${CTF_ADMIN_BASE}/events/${eventId}/scoreboard/`;
export const ctfAdminEventMonitoringPath = (eventId: string): string =>
  `${CTF_ADMIN_BASE}/events/${eventId}/monitoring/`;
export const ctfAdminEventRangesPath = (eventId: string): string => `${CTF_ADMIN_BASE}/events/${eventId}/ranges/`;
export const ctfAdminEventNotificationsPath = (eventId: string): string =>
  `${CTF_ADMIN_BASE}/events/${eventId}/notifications/`;
export const ctfAdminEventBracketsPath = (eventId: string): string => `${CTF_ADMIN_BASE}/events/${eventId}/brackets/`;
