// Standalone documentation Mermaid renderer (#1520, ADR-036).
//
// Bundled by frontend/vite.mermaid.config.ts into a single self-contained,
// content-hashed asset served same-origin by WhiteNoise, so the documentation
// pages no longer load Mermaid from a public package CDN. This module owns the
// theme, the code-block -> diagram conversion, and the render trigger that used
// to live inline in templates/documentation/base.html.

import mermaid from "mermaid";

const THEME_VARIABLES = {
  primaryColor: "#00cc66",
  primaryTextColor: "#eaebeb",
  primaryBorderColor: "#333",
  lineColor: "#666",
  secondaryColor: "#151515",
  tertiaryColor: "#1f1f1f",
  background: "#151515",
  mainBkg: "#151515",
  nodeBorder: "#333",
  clusterBkg: "#1f1f1f",
  clusterBorder: "#333",
  titleColor: "#eaebeb",
  edgeLabelBackground: "#1f1f1f",
} as const;

// Diagram keywords used to detect Mermaid in unlabelled code blocks.
const DIAGRAM_PREFIXES = [
  "flowchart",
  "sequenceDiagram",
  "graph",
  "classDiagram",
  "stateDiagram",
  "erDiagram",
  "gantt",
  "pie",
];

function replaceWithDiagram(block: Element, source: string): void {
  const pre = block.parentElement;
  if (!pre?.parentNode) {
    return;
  }
  const div = document.createElement("div");
  div.className = "mermaid";
  div.textContent = source;
  pre.replaceWith(div);
}

function convertCodeBlocksToDiagrams(): void {
  document.querySelectorAll("pre code.language-mermaid").forEach((block) => {
    replaceWithDiagram(block, block.textContent ?? "");
  });
  document.querySelectorAll("pre code").forEach((block) => {
    const text = (block.textContent ?? "").trim();
    if (DIAGRAM_PREFIXES.some((prefix) => text.startsWith(prefix))) {
      replaceWithDiagram(block, text);
    }
  });
}

function render(): void {
  mermaid.initialize({ startOnLoad: false, theme: "dark", themeVariables: THEME_VARIABLES });
  convertCodeBlocksToDiagrams();
  mermaid.run().catch(() => {
    // Diagram render failures are non-fatal for the surrounding documentation.
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", render);
} else {
  render();
}
