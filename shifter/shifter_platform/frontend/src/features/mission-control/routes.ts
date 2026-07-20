/**
 * Mission Control client-route paths (#1370).
 *
 * Mission Control still has a live legacy Django app at these same paths
 * (`mission_control/urls.py`); every path builder here must match its page
 * paths exactly, trailing slash included, so a client-router deep link or
 * refresh resolves the same page the Django host would have served (the
 * backend's catch-all serves the SPA shell for any non-excluded
 * `/mission-control/*` path once both SPA flags are on). Unlike Risk Register
 * (SPA-native, no legacy counterpart), these paths are not free to change
 * shape independently of the backend.
 */
export const MISSION_CONTROL_BASE = "/mission-control";

export const missionControlDashboardPath = (): string => `${MISSION_CONTROL_BASE}/`;
export const missionControlHistoryPath = (): string => `${MISSION_CONTROL_BASE}/ranges/`;
export const missionControlLaunchPath = (): string => `${MISSION_CONTROL_BASE}/launch/`;
export const missionControlRangeDetailPath = (requestId: string): string =>
  `${MISSION_CONTROL_BASE}/ranges/${requestId}/`;
/** `instanceUuid` identifies which instance's terminal to open (see `TerminalPage`). */
export const missionControlTerminalPath = (instanceUuid: string): string =>
  `${MISSION_CONTROL_BASE}/terminal/${instanceUuid}/`;
export const missionControlAgentsPath = (): string => `${MISSION_CONTROL_BASE}/agents/`;
export const missionControlNgfwListPath = (): string => `${MISSION_CONTROL_BASE}/ngfw/`;
export const missionControlNgfwDetailPath = (appId: string): string => `${MISSION_CONTROL_BASE}/ngfw/${appId}/`;
export const missionControlNgfwWizardPath = (): string => `${MISSION_CONTROL_BASE}/ngfw/setup/`;
export const missionControlCredentialsPath = (): string => `${MISSION_CONTROL_BASE}/credentials/`;
