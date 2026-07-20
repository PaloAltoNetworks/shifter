import { accountOriginLabel } from "./format";

// Apple-style system colors used only as a small supplementary dot; the text
// label carries the meaning, so status is never color-only (WCAG 2.1 AA).
const CHIP =
  "inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-0.5 text-xs font-medium";

const ORIGIN_DOT: Record<string, string> = {
  provider: "#0a84ff",
  local: "#8e8e93",
  ctf: "#ff9f0a",
};

export function AccountOriginBadge({ origin }: Readonly<{ origin: string }>) {
  return (
    <span className={`${CHIP} text-foreground/85`}>
      <span
        className="size-1.5 rounded-full"
        style={{ backgroundColor: ORIGIN_DOT[origin] ?? ORIGIN_DOT.local }}
        aria-hidden="true"
      />
      {accountOriginLabel(origin)}
    </span>
  );
}

export function AccountStatusBadge({ isActive, isDeleted }: Readonly<{ isActive: boolean; isDeleted: boolean }>) {
  if (isDeleted) {
    return <span className={`${CHIP} text-muted-foreground`}>Deleted</span>;
  }
  return (
    <span className={`${CHIP} ${isActive ? "text-foreground/85" : "text-muted-foreground"}`}>
      <span
        className="size-1.5 rounded-full"
        style={{ backgroundColor: isActive ? "#30d158" : "#8e8e93" }}
        aria-hidden="true"
      />
      {isActive ? "Active" : "Disabled"}
    </span>
  );
}

export function RoleBadge({ label }: Readonly<{ label: string }>) {
  return <span className={`${CHIP} text-muted-foreground`}>{label}</span>;
}
