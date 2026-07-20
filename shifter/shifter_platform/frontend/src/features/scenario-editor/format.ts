import { titleCase } from "@/lib/format";

import type { ScenarioSource } from "@/api/types";

export { titleCase };

/** Human label for a scenario `source` classification. */
export const SOURCE_LABELS: Record<ScenarioSource, string> = {
  builtin: "Built-in",
  custom: "Custom",
  aces: "ACES",
  ctf: "CTF",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source as ScenarioSource] ?? titleCase(source);
}

/** Trigger a client-side download of text content as a file. */
export function downloadTextFile(filename: string, content: string): void {
  const blob = new Blob([content], { type: "text/yaml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
