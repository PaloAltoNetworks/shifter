/**
 * Guarded browser persistence for terminal-workspace presentation state (#1661).
 *
 * Reuses the legacy `TerminalManager` keys (`static/js/terminal-layout.js`) so a
 * rollback between the SPA workspace and the Django terminal page keeps the
 * user's layout and pane assignments coherent. Every read and write fails soft:
 * storage may be unavailable (privacy mode, disabled cookies) or reject a write
 * (quota), and neither may block terminal access.
 *
 * Only bounded, non-secret presentation preferences live here. Range data,
 * terminal output, connection status, and signed Guacamole URLs never are
 * persisted. Stored values are untrusted on read — layouts are allowlisted by
 * `normalizeLayout` and target ids are reconciled against the live inventory by
 * `reconcileSelection` before anything connects.
 *
 * Modeled on `lib/theme.ts`'s guarded `store()` accessor.
 */
import { normalizeLayout, type TerminalLayout, type WorkspaceSelection } from "./terminalWorkspaceState";

const LAYOUT_KEY = "terminal-layout";
const ACTIVE_TAB_KEY = "terminal-active-tab";
const LEFT_PANE_KEY = "terminal-left-pane";
const RIGHT_PANE_KEY = "terminal-right-pane";
// SPA-only: legacy used Split.js's own sizing and had no equivalent key.
const SPLIT_SIZES_KEY = "terminal-split-sizes";

function store(): Storage | null {
  try {
    return globalThis.localStorage;
  } catch {
    return null;
  }
}

function read(key: string): string | null {
  try {
    return store()?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

/** Write `value`, or remove the key when `value` is null. Never throws. */
function write(key: string, value: string | null): void {
  try {
    if (value === null) {
      store()?.removeItem(key);
    } else {
      store()?.setItem(key, value);
    }
  } catch {
    // Storage unavailable or over quota: preferences are disposable.
  }
}

export interface WorkspacePreferences extends WorkspaceSelection {
  layout: TerminalLayout;
}

export function readWorkspacePreferences(): WorkspacePreferences {
  return {
    layout: normalizeLayout(read(LAYOUT_KEY)),
    activeUuid: read(ACTIVE_TAB_KEY),
    leftUuid: read(LEFT_PANE_KEY),
    rightUuid: read(RIGHT_PANE_KEY),
  };
}

export function writeLayout(layout: TerminalLayout): void {
  write(LAYOUT_KEY, layout);
}

export function writeSelection(selection: WorkspaceSelection): void {
  write(ACTIVE_TAB_KEY, selection.activeUuid);
  write(LEFT_PANE_KEY, selection.leftUuid);
  write(RIGHT_PANE_KEY, selection.rightUuid);
}

/**
 * The persisted split-pane sizes, or null when absent or malformed.
 *
 * `react-resizable-panels` keys its `Layout` by panel id with numeric sizes;
 * anything else in storage is discarded rather than passed to the group.
 */
export function readSplitSizes(): Record<string, number> | null {
  const raw = read(SPLIT_SIZES_KEY);
  if (raw === null) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return null;
  const entries = Object.entries(parsed as Record<string, unknown>);
  if (entries.length === 0 || !entries.every(([, size]) => typeof size === "number" && Number.isFinite(size))) {
    return null;
  }
  return Object.fromEntries(entries) as Record<string, number>;
}

export function writeSplitSizes(sizes: Record<string, number>): void {
  try {
    write(SPLIT_SIZES_KEY, JSON.stringify(sizes));
  } catch {
    // Unserializable input is a caller bug, not a reason to break the layout.
  }
}
