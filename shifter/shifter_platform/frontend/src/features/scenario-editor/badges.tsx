import { sourceLabel } from "./format";

const CHIP =
  "inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-0.5 text-xs font-medium";

// Supplementary dot only; the text label carries the meaning (not color-only).
const SOURCE_DOT: Record<string, string> = {
  raes: "#bf5af2",
};

export function SourceBadge({ source }: Readonly<{ source: string }>) {
  return (
    <span className={`${CHIP} text-foreground/85`}>
      <span
        className="size-1.5 rounded-full"
        style={{ backgroundColor: SOURCE_DOT[source] ?? "#8e8e93" }}
        aria-hidden="true"
      />
      {sourceLabel(source)}
    </span>
  );
}

export function EnabledBadge({ enabled }: Readonly<{ enabled: boolean }>) {
  return <span className={`${CHIP} text-muted-foreground`}>{enabled ? "Enabled" : "Disabled"}</span>;
}

export function StaffOnlyBadge() {
  return <span className={`${CHIP} text-muted-foreground`}>Staff only</span>;
}
