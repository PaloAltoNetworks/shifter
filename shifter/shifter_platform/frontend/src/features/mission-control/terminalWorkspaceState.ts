/**
 * Terminal-workspace view model: layout mode + target assignments (#1661).
 *
 * Pure functions only. Route params and `localStorage` values are untrusted
 * presentation input — they are reconciled against the live, actor-filtered
 * target inventory here before any pane opens a WebSocket or requests a
 * Guacamole session. This module never validates ownership; that stays with
 * `SSHConsumer` / `engine.services.connect_terminal` and the Guacamole views.
 */
import type { ConsoleTarget } from "./consoleTargets";

/** The closed presentation union. `tabs` is the default, matching legacy. */
export type TerminalLayout = "tabs" | "split";

const LAYOUTS: readonly TerminalLayout[] = ["tabs", "split"];

/** Allowlist a stored/toggled layout value, defaulting to `tabs`. */
export function normalizeLayout(value: string | null | undefined): TerminalLayout {
  return LAYOUTS.find((layout) => layout === value) ?? "tabs";
}

export interface WorkspaceSelection {
  /** Target shown in `tabs` mode. */
  activeUuid: string | null;
  /** Left `split` pane target. */
  leftUuid: string | null;
  /** Right `split` pane target; null when the range has fewer than two targets. */
  rightUuid: string | null;
}

/**
 * Assign `uuid` to `pane`, swapping the panes when the other pane already
 * shows it.
 *
 * The two split panes must stay distinct, but silently reverting the select to
 * its previous value reads as a broken control. Swapping is what the user meant
 * and preserves the invariant.
 */
export function swapIfDuplicate(
  selection: WorkspaceSelection,
  pane: "left" | "right",
  uuid: string,
): WorkspaceSelection {
  const isLeft = pane === "left";
  const other = isLeft ? selection.rightUuid : selection.leftUuid;
  const current = isLeft ? selection.leftUuid : selection.rightUuid;
  // When the other pane already shows `uuid`, it takes this pane's current
  // target (a swap); otherwise the other pane is untouched.
  const displaced = other === uuid ? current : other;
  return isLeft
    ? { ...selection, leftUuid: uuid, rightUuid: displaced }
    : { ...selection, leftUuid: displaced, rightUuid: uuid };
}

function memberOrNull(targets: readonly ConsoleTarget[], uuid: string | null | undefined): string | null {
  return targets.some((target) => target.uuid === uuid) ? (uuid as string) : null;
}

/**
 * Reconcile preferred (stored or deep-linked) selections against `targets`.
 *
 * Stale or absent values fall back deterministically: the first target for the
 * active tab and left pane, and the first *distinct* target for the right pane.
 * The two split panes never resolve to the same target while another one
 * exists, so split mode cannot open two sockets to one instance just to fill
 * both slots.
 */
export function reconcileSelection(
  targets: readonly ConsoleTarget[],
  preferred: Partial<WorkspaceSelection>,
): WorkspaceSelection {
  const first = targets[0]?.uuid ?? null;
  if (first === null) {
    return { activeUuid: null, leftUuid: null, rightUuid: null };
  }

  const leftUuid = memberOrNull(targets, preferred.leftUuid) ?? first;
  const preferredRight = memberOrNull(targets, preferred.rightUuid);
  const rightUuid =
    preferredRight !== null && preferredRight !== leftUuid
      ? preferredRight
      : (targets.find((target) => target.uuid !== leftUuid)?.uuid ?? null);

  return {
    activeUuid: memberOrNull(targets, preferred.activeUuid) ?? first,
    leftUuid,
    rightUuid,
  };
}
