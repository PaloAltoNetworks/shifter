/**
 * Client-side tag/topic filtering shared by the participant and organizer
 * challenge listings (CTF-113 / CTF-119). Filtering happens in the browser:
 * event challenge lists are small and this matches the legacy UX.
 */
import { Button } from "@/components/ui/button";

export interface Labeled {
  tags?: readonly string[] | null;
  topics?: readonly string[] | null;
}

/** Distinct, sorted label values across challenges for one axis. */
export function distinctLabels(challenges: readonly Labeled[], axis: "tags" | "topics"): string[] {
  const values = new Set<string>();
  for (const challenge of challenges) {
    for (const value of challenge[axis] ?? []) values.add(value);
  }
  return [...values].sort((a, b) => a.localeCompare(b));
}

/** Return the items matching the active tag and topic filters. */
export function filterByLabels<T extends Labeled>(items: readonly T[], activeTag: string | null, activeTopic: string | null): T[] {
  return items.filter(
    (item) =>
      (activeTag === null || (item.tags ?? []).includes(activeTag)) &&
      (activeTopic === null || (item.topics ?? []).includes(activeTopic)),
  );
}

export function LabelFilterRow({
  axis,
  labels,
  active,
  onToggle,
}: Readonly<{
  axis: "tags" | "topics";
  labels: string[];
  active: string | null;
  onToggle: (value: string) => void;
}>) {
  if (labels.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label={`Filter by ${axis === "tags" ? "tag" : "topic"}`}>
      <span className="text-xs text-muted-foreground">{axis === "tags" ? "Tags:" : "Topics:"}</span>
      {labels.map((label) => (
        <Button
          key={label}
          type="button"
          size="sm"
          variant={active === label ? "default" : "outline"}
          className="h-7 rounded-full px-3 text-xs"
          aria-pressed={active === label}
          onClick={() => onToggle(label)}
        >
          {label}
        </Button>
      ))}
    </div>
  );
}
