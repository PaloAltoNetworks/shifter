import { INTENT_DOT, type Intent } from "@/app/state-map";

/**
 * Status chip that conveys an intent by dot + text (never colour alone), so it
 * meets AA non-color-only status. Reused across surfaces via the state-mapping
 * seam (`app/state-map`).
 */
export function StatusChip({ intent, label }: Readonly<{ intent: Intent; label: string }>) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-0.5 text-xs font-medium text-foreground/85">
      <span
        className="size-1.5 rounded-full"
        style={{ backgroundColor: INTENT_DOT[intent] }}
        aria-hidden="true"
      />
      {label}
    </span>
  );
}
