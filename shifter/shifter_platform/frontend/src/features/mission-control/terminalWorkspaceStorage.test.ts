import { afterEach, describe, expect, it, vi } from "vitest";

import {
  readSplitSizes,
  readWorkspacePreferences,
  writeLayout,
  writeSelection,
  writeSplitSizes,
} from "./terminalWorkspaceStorage";

afterEach(() => {
  globalThis.localStorage.clear();
  vi.restoreAllMocks();
});

describe("readWorkspacePreferences", () => {
  it("reads the legacy TerminalManager keys so SPA/legacy rollback stays coherent", () => {
    globalThis.localStorage.setItem("terminal-layout", "split");
    globalThis.localStorage.setItem("terminal-active-tab", "a");
    globalThis.localStorage.setItem("terminal-left-pane", "b");
    globalThis.localStorage.setItem("terminal-right-pane", "c");

    expect(readWorkspacePreferences()).toEqual({
      layout: "split",
      activeUuid: "a",
      leftUuid: "b",
      rightUuid: "c",
    });
  });

  it("normalizes an unknown stored layout to tabs rather than trusting it", () => {
    globalThis.localStorage.setItem("terminal-layout", "golden-layout");
    expect(readWorkspacePreferences().layout).toBe("tabs");
  });

  it("returns empty defaults on a cold start", () => {
    expect(readWorkspacePreferences()).toEqual({
      layout: "tabs",
      activeUuid: null,
      leftUuid: null,
      rightUuid: null,
    });
  });

  it("fails soft to defaults when storage access throws", () => {
    vi.spyOn(globalThis.Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage disabled");
    });
    expect(readWorkspacePreferences()).toEqual({
      layout: "tabs",
      activeUuid: null,
      leftUuid: null,
      rightUuid: null,
    });
  });
});

describe("writeLayout / writeSelection", () => {
  it("persists the layout and each pane assignment under the legacy keys", () => {
    writeLayout("split");
    writeSelection({ activeUuid: "a", leftUuid: "b", rightUuid: "c" });

    expect(globalThis.localStorage.getItem("terminal-layout")).toBe("split");
    expect(globalThis.localStorage.getItem("terminal-active-tab")).toBe("a");
    expect(globalThis.localStorage.getItem("terminal-left-pane")).toBe("b");
    expect(globalThis.localStorage.getItem("terminal-right-pane")).toBe("c");
  });

  it("clears a key rather than storing null when a pane has no target", () => {
    globalThis.localStorage.setItem("terminal-right-pane", "stale");
    writeSelection({ activeUuid: "a", leftUuid: "a", rightUuid: null });
    expect(globalThis.localStorage.getItem("terminal-right-pane")).toBeNull();
  });

  it("does not throw when storage rejects the write (quota, privacy mode)", () => {
    vi.spyOn(globalThis.Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    expect(() => writeLayout("split")).not.toThrow();
    expect(() => writeSelection({ activeUuid: "a", leftUuid: "a", rightUuid: null })).not.toThrow();
  });
});

describe("split pane sizes", () => {
  it("round-trips a bounded numeric layout", () => {
    writeSplitSizes({ left: 60, right: 40 });
    expect(readSplitSizes()).toEqual({ left: 60, right: 40 });
  });

  it("rejects malformed or non-numeric stored sizes instead of feeding them to the layout", () => {
    globalThis.localStorage.setItem("terminal-split-sizes", "not json");
    expect(readSplitSizes()).toBeNull();

    globalThis.localStorage.setItem("terminal-split-sizes", JSON.stringify({ left: "wide" }));
    expect(readSplitSizes()).toBeNull();

    globalThis.localStorage.setItem("terminal-split-sizes", JSON.stringify([50, 50]));
    expect(readSplitSizes()).toBeNull();
  });
});
