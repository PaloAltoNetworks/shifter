import { beforeEach, describe, expect, it, vi } from "vitest";

const initialize = vi.fn();
const run = vi.fn(() => Promise.resolve());

vi.mock("mermaid", () => ({ default: { initialize, run } }));

beforeEach(() => {
  vi.resetModules();
  initialize.mockClear();
  run.mockClear();
  document.body.innerHTML = "";
});

describe("mermaid documentation renderer", () => {
  it("converts language-mermaid code blocks into diagram nodes and renders", async () => {
    document.body.innerHTML = `<pre><code class="language-mermaid">flowchart TD; A--&gt;B</code></pre>`;

    await import("./mermaid-entry");

    const diagram = document.querySelector("div.mermaid");
    expect(diagram).not.toBeNull();
    expect(diagram?.textContent).toContain("flowchart TD");
    expect(initialize).toHaveBeenCalledTimes(1);
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("detects an unlabelled code block that starts with a diagram keyword", async () => {
    document.body.innerHTML = `<pre><code>sequenceDiagram\n  A->>B: hi</code></pre>`;

    await import("./mermaid-entry");

    expect(document.querySelector("div.mermaid")?.textContent).toContain("sequenceDiagram");
  });

  it("leaves ordinary code blocks untouched", async () => {
    document.body.innerHTML = `<pre><code>const x = 1;</code></pre>`;

    await import("./mermaid-entry");

    expect(document.querySelector("div.mermaid")).toBeNull();
  });
});
