/**
 * Domain-status to design-system-intent mapping (#1369, #1368).
 *
 * One mapping translates domain values (range/provisioning lifecycle, event
 * lifecycle) into design-system intents plus accessible labels. Intents render
 * domain state; they do not define the state machine. The next status value
 * adds one entry here rather than a new badge component, colour token, or state
 * machine (the state-mapping seam). Backend state names are preserved in labels
 * (no invented friendly copy that hides operator risk); status is conveyed by
 * icon/dot plus text, never colour alone.
 */
export type Intent = "neutral" | "success" | "warning" | "danger" | "pending" | "muted";

/** Small supplementary dot colour per intent (Apple system palette). */
export const INTENT_DOT: Record<Intent, string> = {
  neutral: "#8e8e93",
  success: "#30d158",
  warning: "#ff9f0a",
  danger: "#ff453a",
  pending: "#0a84ff",
  muted: "#48484a",
};

export interface StatusMapping {
  readonly intent: Intent;
  readonly label: string;
}

function titleize(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

// #1368 range/provisioning mapping. Keys are normalized backend status names.
// `pending`/`pausing`/`paused`/`resuming`/`destroyed` are the real cyberscript
// `ResourceStatus` values (#1370, `cyberscript/enums.py`); the others predate
// that enum's adoption and are kept for compatibility with any caller still
// passing the older friendly names.
const RANGE_INTENT: Record<string, Intent> = {
  pending: "pending",
  provisioning: "pending",
  available: "success",
  running: "success",
  ready: "success",
  pausing: "pending",
  paused: "warning",
  resuming: "pending",
  unhealthy: "danger",
  failed: "danger",
  error: "danger",
  deprovisioning: "warning",
  destroying: "warning",
  destroyed: "muted",
};

// #1368 event mapping.
const EVENT_INTENT: Record<string, Intent> = {
  draft: "neutral",
  active: "success",
  ended: "muted",
};

function mapStatus(status: string | null, table: Record<string, Intent>, emptyLabel: string): StatusMapping {
  if (!status) {
    return { intent: "muted", label: emptyLabel };
  }
  const key = status.trim().toLowerCase();
  return { intent: table[key] ?? "neutral", label: titleize(status) };
}

/** Map a range/provisioning status to an intent and accessible label. */
export function rangeStatusMapping(status: string | null): StatusMapping {
  return mapStatus(status, RANGE_INTENT, "No active range");
}

/** Map a CTF event status to an intent and accessible label. */
export function eventStatusMapping(status: string | null): StatusMapping {
  return mapStatus(status, EVENT_INTENT, "No active event");
}
