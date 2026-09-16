import { describe, expect, it } from "vitest";

import type { InstancePresentation, RangePresentation } from "@/api/types";

import { consoleTargetsOf, isConsoleCapable } from "./consoleTargets";

function instance(overrides: Partial<InstancePresentation> = {}): InstancePresentation {
  return {
    uuid: "11111111-1111-1111-1111-111111111111",
    name: "web-01",
    role: "victim",
    os_type: "ubuntu",
    join_domain: false,
    ami_key: null,
    private_ip: "10.0.1.10",
    ...overrides,
  } as InstancePresentation;
}

function range(instances: InstancePresentation[]): RangePresentation {
  return { instances } as RangePresentation;
}

describe("isConsoleCapable", () => {
  it("accepts a non-NGFW instance that carries a uuid", () => {
    expect(isConsoleCapable(instance())).toBe(true);
  });

  it("rejects an NGFW instance, which is reached through the NGFW app-id path instead", () => {
    expect(isConsoleCapable(instance({ role: "ngfw" as InstancePresentation["role"] }))).toBe(false);
  });

  it("rejects an instance with no uuid, which has no terminal or Guacamole target", () => {
    expect(isConsoleCapable(instance({ uuid: null }))).toBe(false);
  });
});

describe("consoleTargetsOf", () => {
  it("keeps only console-capable instances and preserves range order", () => {
    const targets = consoleTargetsOf(
      range([
        instance({ uuid: "a", name: "web-01" }),
        instance({ uuid: null, name: "pending" }),
        instance({ uuid: "b", name: "fw", role: "ngfw" as InstancePresentation["role"] }),
        instance({ uuid: "c", name: "win-dc01" }),
      ]),
    );
    expect(targets.map((target) => target.uuid)).toEqual(["a", "c"]);
  });

  it("returns an empty list when there is no range yet", () => {
    expect(consoleTargetsOf(null)).toEqual([]);
    expect(consoleTargetsOf(undefined)).toEqual([]);
  });
});
