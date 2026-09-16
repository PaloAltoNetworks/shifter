import { titleCase } from "@/lib/format";

import type { ScenarioSource } from "@/api/types";

export { titleCase };

/** Human label for a scenario `source` classification. */
export const SOURCE_LABELS: Record<ScenarioSource, string> = {
  raes: "RAES",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source as ScenarioSource] ?? titleCase(source);
}
