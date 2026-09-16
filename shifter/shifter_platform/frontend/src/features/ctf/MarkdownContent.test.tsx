import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { MarkdownContent } from "./MarkdownContent";

/** The href the first rendered anchor carries, or "" when the element/attribute is absent. */
function anchorHref(container: HTMLElement): string {
  return container.querySelector("a")?.getAttribute("href") ?? "";
}

describe("MarkdownContent (safe render)", () => {
  it("does not inject raw HTML script tags", () => {
    const { container } = render(<MarkdownContent text={"Hi <script>alert(1)</script> there"} />);
    expect(container.querySelector("script")).toBeNull();
  });

  // The renderer neutralizes any non-allowlisted scheme to an empty href, so the
  // tests assert that exact safe outcome rather than a per-scheme prefix check.
  it("neutralizes a javascript: link to an empty href", () => {
    const { container } = render(<MarkdownContent text={"[click](javascript:alert(1))"} />);
    expect(anchorHref(container)).toBe("");
  });

  it("neutralizes a data: link to an empty href", () => {
    const { container } = render(<MarkdownContent text={"[x](data:text/html;base64,PHNjcmlwdD4=)"} />);
    expect(anchorHref(container)).toBe("");
  });

  it("neutralizes a vbscript: link to an empty href", () => {
    const { container } = render(<MarkdownContent text={"[x](vbscript:msgbox(1))"} />);
    expect(anchorHref(container)).toBe("");
  });

  it("keeps safe https links intact", () => {
    const { container } = render(<MarkdownContent text={"[docs](https://example.test/guide)"} />);
    expect(anchorHref(container)).toBe("https://example.test/guide");
  });

  it("renders images by default for existing consumers", () => {
    const { container } = render(<MarkdownContent text={"![diagram](https://example.test/net.png)"} />);
    expect(container.querySelector("img")).not.toBeNull();
  });

  it("drops images when the caller disallows them (briefing policy)", () => {
    const { container } = render(
      <MarkdownContent text={"![diagram](https://example.test/net.png)"} disallowedElements={["img"]} />,
    );
    expect(container.querySelector("img")).toBeNull();
  });

  it("neutralizes an unsafe image source to an empty src", () => {
    const { container } = render(<MarkdownContent text={"![x](javascript:alert(1))"} />);
    expect(container.querySelector("img")?.getAttribute("src") ?? "").toBe("");
  });

  it("neutralizes a scheme smuggled past a naive prefix test with an entity-encoded tab", () => {
    // `jav<TAB>ascript:` — a browser strips the tab and executes it; the URL
    // policy must reject it (empty href) before it reaches the DOM.
    const { container } = render(<MarkdownContent text={"[open](<jav&#x09;ascript:alert(1)>)"} />);
    expect(anchorHref(container)).toBe("");
  });

  it("neutralizes a scheme smuggled with an entity-encoded newline", () => {
    const { container } = render(<MarkdownContent text={"[open](<jav&#x0a;ascript:alert(1)>)"} />);
    expect(anchorHref(container)).toBe("");
  });
});
