import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  REGION,
  LOG_GROUPS,
  getProfile,
  resolveLogGroup,
  buildInstanceFilters,
} from "./lib.js";

// ---------------------------------------------------------------------------
// REGION constant
// ---------------------------------------------------------------------------
describe("REGION", () => {
  it("is us-east-2", () => {
    assert.equal(REGION, "us-east-2");
  });
});

// ---------------------------------------------------------------------------
// LOG_GROUPS mapping
// ---------------------------------------------------------------------------
describe("LOG_GROUPS", () => {
  it("maps portal component to correct log group pattern", () => {
    assert.equal(LOG_GROUPS.portal.dev, "/portal/dev-portal");
    assert.equal(LOG_GROUPS.portal.prod, "/portal/prod-portal");
  });

  it("maps provisioner component to correct log group", () => {
    assert.equal(
      LOG_GROUPS.provisioner.dev,
      "/ecs/dev-portal-pulumi-provisioner"
    );
    assert.equal(
      LOG_GROUPS.provisioner.prod,
      "/ecs/prod-portal-pulumi-provisioner"
    );
  });

  it("maps guacamole client component", () => {
    assert.equal(
      LOG_GROUPS["guacamole-client"].dev,
      "/ecs/dev-portal-guacamole-client"
    );
  });

  it("maps guacd component", () => {
    assert.equal(LOG_GROUPS.guacd.dev, "/ecs/dev-portal-guacd");
  });

  it("maps network firewall logs", () => {
    assert.equal(
      LOG_GROUPS["network-firewall"].dev,
      "/aws/network-firewall/dev-range"
    );
  });

  it("maps rds logs", () => {
    assert.equal(
      LOG_GROUPS.rds.dev,
      "/aws/rds/instance/dev-portal-db/postgresql"
    );
  });
});

// ---------------------------------------------------------------------------
// getProfile
// ---------------------------------------------------------------------------
describe("getProfile", () => {
  const profiles = { dev: "dev-profile", prod: "prod-profile" };

  it("returns the correct profile for dev", () => {
    assert.equal(getProfile(profiles, "dev"), "dev-profile");
  });

  it("returns the correct profile for prod", () => {
    assert.equal(getProfile(profiles, "prod"), "prod-profile");
  });

  it("throws when profile is not set", () => {
    assert.throws(() => getProfile({}, "dev"), /AWS profile not set for dev/);
  });

  it("includes env var name in error message", () => {
    assert.throws(
      () => getProfile({}, "prod"),
      /PANW_SHIFTER_PROD_PROFILE/
    );
  });
});

// ---------------------------------------------------------------------------
// resolveLogGroup
// ---------------------------------------------------------------------------
describe("resolveLogGroup", () => {
  it("resolves a known component to its log group for dev", () => {
    assert.equal(
      resolveLogGroup("provisioner", "dev"),
      "/ecs/dev-portal-pulumi-provisioner"
    );
  });

  it("resolves a known component to its log group for prod", () => {
    assert.equal(resolveLogGroup("portal", "prod"), "/portal/prod-portal");
  });

  it("returns the input unchanged if not a known component", () => {
    assert.equal(
      resolveLogGroup("/custom/log-group", "dev"),
      "/custom/log-group"
    );
  });

  it("returns the input unchanged for arbitrary log group paths", () => {
    assert.equal(
      resolveLogGroup("/ecs/my-service", "prod"),
      "/ecs/my-service"
    );
  });
});

// ---------------------------------------------------------------------------
// buildInstanceFilters
// ---------------------------------------------------------------------------
describe("buildInstanceFilters", () => {
  it("returns state filter only when no name_filter given", () => {
    const filters = buildInstanceFilters({});
    assert.deepEqual(filters, [
      { Name: "instance-state-name", Values: ["pending", "running", "stopping", "stopped"] },
    ]);
  });

  it("adds a Name tag filter when name_filter is provided", () => {
    const filters = buildInstanceFilters({ name_filter: "*portal*" });
    assert.equal(filters.length, 2);
    assert.deepEqual(filters[0], {
      Name: "tag:Name",
      Values: ["*portal*"],
    });
  });

  it("includes terminated instances when include_terminated is true", () => {
    const filters = buildInstanceFilters({ include_terminated: true });
    const stateFilter = filters.find(
      (f) => f.Name === "instance-state-name"
    );
    assert.ok(stateFilter.Values.includes("terminated"));
  });

  it("excludes terminated by default", () => {
    const filters = buildInstanceFilters({});
    const stateFilter = filters.find(
      (f) => f.Name === "instance-state-name"
    );
    assert.ok(!stateFilter.Values.includes("terminated"));
  });
});
