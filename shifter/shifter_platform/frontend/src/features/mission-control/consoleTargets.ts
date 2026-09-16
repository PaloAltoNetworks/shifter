/**
 * Which range instances can host an in-app console (#1661).
 *
 * NGFW instances are provisioned and managed through a completely separate
 * backend path keyed by CMS App id, not instance UUID
 * (`engine.services.connect_ngfw_terminal`, `/mission-control/ngfw/<app_id>/
 * ssh-url/`) — distinct from `connect_terminal` /
 * `_resolve_and_build_{rdp,range_ssh}_url`, which every other role uses
 * uniformly regardless of os_type (Windows just skips the tmux session id).
 * So NGFW rows never carry terminal/Guacamole actions here; NGFW access lives
 * on the NGFW surfaces (`missionControlNgfwDetailPath`).
 *
 * Shared by `InstanceTable` (per-row actions) and the terminal workspace
 * (`TerminalWorkspacePage`) so both surfaces agree on what a console target is.
 */
import type { InstancePresentation, RangePresentation } from "@/api/types";

/** A range instance that can host a terminal or Guacamole session. */
export type ConsoleTarget = InstancePresentation & { uuid: string };

export function isConsoleCapable(instance: InstancePresentation): instance is ConsoleTarget {
  return instance.role !== "ngfw" && instance.uuid != null;
}

/**
 * The console-capable instances of a range, in the order the API returned them.
 *
 * The caller must pass the actor-filtered `RangePresentation` from
 * `useCurrentRange()`; this helper narrows presentation capability only and is
 * never an authorization decision (the backend re-checks ownership on every
 * terminal and Guacamole call).
 */
export function consoleTargetsOf(range: RangePresentation | null | undefined): ConsoleTarget[] {
  return (range?.instances ?? []).filter(isConsoleCapable);
}
