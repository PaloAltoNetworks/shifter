import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { REGION, getProfile } from "./lib.js";

describe("REGION", () => {
  it("is us-east-2", () => {
    assert.equal(REGION, "us-east-2");
  });
});

describe("getProfile", () => {
  const profiles = { dev: "dev-profile", prod: "prod-profile" };

  it("returns the profile for a valid env", () => {
    assert.equal(getProfile(profiles, "dev"), "dev-profile");
    assert.equal(getProfile(profiles, "prod"), "prod-profile");
  });

  it("throws for missing profile", () => {
    assert.throws(
      () => getProfile({}, "dev"),
      /AWS profile not set for dev/
    );
  });

  it("throws with env name in error message", () => {
    assert.throws(
      () => getProfile({}, "prod"),
      /PANW_SHIFTER_PROD_PROFILE/
    );
  });
});
