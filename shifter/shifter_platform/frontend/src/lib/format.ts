/** Shared presentation-formatting helpers reused across SPA feature workspaces (#1373). */

/** Title-case a string by capitalizing its first character. */
export function titleCase(value: string): string {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

/** Format an ISO timestamp for display; renders an em dash when absent or unparsable. */
export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
