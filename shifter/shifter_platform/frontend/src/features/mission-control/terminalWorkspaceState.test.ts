import { describe, expect, it } from "vitest";

import type { InstancePresentation } from "@/api/types";

import type { ConsoleTarget } from "./consoleTargets";
import { normalizeLayout, reconcileSelection, swapIfDuplicate } from "./terminalWorkspaceState";

function target(uuid: string): ConsoleTarget {
  return {
    uuid,
    name: `host-${uuid}`,
    role: "victim",
    os_type: "ubuntu",
    join_domain: false,
    ami_key: null,
    private_ip: null,
  } as ConsoleTarget & InstancePresentation;
}

describe("normalizeLayout", () => {
  it("accepts the two allowlisted layout values", () => {
    expect(normalizeLayout("tabs")).toBe("tabs");
    expect(normalizeLayout("split")).toBe("split");
  });

  it("falls back to tabs for absent, malformed, or unknown stored values", () => {
    expect(normalizeLayout(null)).toBe("tabs");
    expect(normalizeLayout(undefined)).toBe("tabs");
    expect(normalizeLayout("")).toBe("tabs");
    expect(normalizeLayout("grid")).toBe("tabs");
    expect(normalizeLayout("__proto__")).toBe("tabs");
  });
});

describe("reconcileSelection", () => {
  const targets = [target("a"), target("b"), target("c")];

  it("keeps preferred selections that are still members of the inventory", () => {
    expect(reconcileSelection(targets, { activeUuid: "b", leftUuid: "c", rightUuid: "a" })).toEqual({
      activeUuid: "b",
      leftUuid: "c",
      rightUuid: "a",
    });
  });

  it("drops a stale target that is no longer in the range and falls back deterministically", () => {
    expect(reconcileSelection(targets, { activeUuid: "gone", leftUuid: "gone", rightUuid: "gone" })).toEqual({
      activeUuid: "a",
      leftUuid: "a",
      rightUuid: "b",
    });
  });

  it("defaults the split panes to the first two distinct targets", () => {
    expect(reconcileSelection(targets, {})).toEqual({ activeUuid: "a", leftUuid: "a", rightUuid: "b" });
  });

  it("never assigns the same target to both split panes when a distinct one exists", () => {
    const reconciled = reconcileSelection(targets, { leftUuid: "b", rightUuid: "b" });
    expect(reconciled.leftUuid).toBe("b");
    expect(reconciled.rightUuid).not.toBe("b");
  });

  it("swaps the panes when a pane is pointed at the device the other pane already shows", () => {
    // Silently snapping the select back to its previous value looks broken;
    // swapping is what the user meant and still keeps the panes distinct.
    expect(swapIfDuplicate({ activeUuid: "a", leftUuid: "a", rightUuid: "b" }, "left", "b")).toEqual({
      activeUuid: "a",
      leftUuid: "b",
      rightUuid: "a",
    });
    expect(swapIfDuplicate({ activeUuid: "a", leftUuid: "a", rightUuid: "b" }, "right", "a")).toEqual({
      activeUuid: "a",
      leftUuid: "b",
      rightUuid: "a",
    });
  });

  it("assigns normally when the chosen device is not already in the other pane", () => {
    expect(swapIfDuplicate({ activeUuid: "a", leftUuid: "a", rightUuid: "b" }, "left", "c")).toEqual({
      activeUuid: "a",
      leftUuid: "c",
      rightUuid: "b",
    });
  });

  it("leaves the right pane empty when the range has only one console target", () => {
    expect(reconcileSelection([target("only")], {})).toEqual({
      activeUuid: "only",
      leftUuid: "only",
      rightUuid: null,
    });
  });

  it("returns an empty selection when the range has no console targets", () => {
    expect(reconcileSelection([], { activeUuid: "a", leftUuid: "a", rightUuid: "b" })).toEqual({
      activeUuid: null,
      leftUuid: null,
      rightUuid: null,
    });
  });
});
