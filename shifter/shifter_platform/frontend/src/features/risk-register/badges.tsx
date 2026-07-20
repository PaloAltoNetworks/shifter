import type { Severity, Status } from "@/api/types";

import { titleCase } from "./format";

// Apple-style system colors, used only as a small supplementary dot (the text
// label carries the meaning, so this is not color-only).
const SEVERITY_DOT: Record<Severity, string> = {
  critical: "#ff453a",
  high: "#ff9f0a",
  medium: "#ffd60a",
  low: "#8e8e93",
};

const CHIP =
  "inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-0.5 text-xs font-medium";

export function SeverityBadge({ severity }: Readonly<{ severity: Severity }>) {
  return (
    <span className={`${CHIP} text-foreground/85`}>
      <span
        className="size-1.5 rounded-full"
        style={{ backgroundColor: SEVERITY_DOT[severity] ?? SEVERITY_DOT.low }}
        aria-hidden="true"
      />
      {titleCase(severity)}
    </span>
  );
}

export function StatusBadge({ status }: Readonly<{ status: Status }>) {
  return <span className={`${CHIP} text-muted-foreground`}>{titleCase(status)}</span>;
}
