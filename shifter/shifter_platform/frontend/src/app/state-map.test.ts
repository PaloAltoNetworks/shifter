import { describe, expect, it } from "vitest";

import { eventStatusMapping, rangeStatusMapping } from "./state-map";

describe("rangeStatusMapping", () => {
  it("maps known lifecycle statuses to operator intents", () => {
    expect(rangeStatusMapping("provisioning").intent).toBe("pending");
    expect(rangeStatusMapping("running").intent).toBe("success");
    expect(rangeStatusMapping("failed").intent).toBe("danger");
    expect(rangeStatusMapping("deprovisioning").intent).toBe("warning");
  });

  it("normalizes case and preserves the backend name as the label", () => {
    const mapping = rangeStatusMapping("UNHEALTHY");
    expect(mapping.intent).toBe("danger");
    expect(mapping.label).toBe("UNHEALTHY");
  });

  it("returns a muted no-range state for null", () => {
    expect(rangeStatusMapping(null)).toEqual({ intent: "muted", label: "No active range" });
  });

  it("falls back to neutral for an unknown status", () => {
    expect(rangeStatusMapping("weird").intent).toBe("neutral");
  });

  it("maps the cyberscript ResourceStatus lifecycle values (#1370)", () => {
    expect(rangeStatusMapping("pending").intent).toBe("pending");
    expect(rangeStatusMapping("pausing").intent).toBe("pending");
    expect(rangeStatusMapping("paused").intent).toBe("warning");
    expect(rangeStatusMapping("resuming").intent).toBe("pending");
    expect(rangeStatusMapping("destroyed").intent).toBe("muted");
  });
});

describe("eventStatusMapping", () => {
  it("maps event lifecycle statuses", () => {
    expect(eventStatusMapping("draft").intent).toBe("neutral");
    expect(eventStatusMapping("active").intent).toBe("success");
    expect(eventStatusMapping("ended").intent).toBe("muted");
  });

  it("returns a muted no-event state for null", () => {
    expect(eventStatusMapping(null)).toEqual({ intent: "muted", label: "No active event" });
  });
});
