import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  getServiceLayer,
  getProfile,
  FORBIDDEN_PATTERN,
  SERVICE_LAYERS,
  LEGACY_TABLE_MAP,
  LOCAL_PORTS,
} from "./lib.js";

describe("getServiceLayer", () => {
  it("maps cms_ tables to Shifter CMS", () => {
    assert.equal(
      getServiceLayer("cms_app"),
      "Shifter CMS (content management)"
    );
    assert.equal(
      getServiceLayer("cms_rangeinstance"),
      "Shifter CMS (content management)"
    );
  });

  it("maps engine_ tables to Shifter Engine", () => {
    assert.equal(
      getServiceLayer("engine_instance"),
      "Shifter Engine (range provisioning)"
    );
  });

  it("maps risk_register_ tables to Risk Register", () => {
    assert.equal(
      getServiceLayer("risk_register_risk"),
      "Risk Register (security tracking)"
    );
  });

  it("maps auth_ tables to Django Auth", () => {
    assert.equal(getServiceLayer("auth_user"), "Django Auth");
  });

  it("maps django_ tables to Django Framework", () => {
    assert.equal(getServiceLayer("django_migrations"), "Django Framework");
  });

  it("maps health_check_ tables to Health Checks", () => {
    assert.equal(getServiceLayer("health_check_db_testmodel"), "Health Checks");
  });

  it("maps legacy mission_control_range to Engine", () => {
    assert.equal(
      getServiceLayer("mission_control_range"),
      "Shifter Engine (range provisioning)"
    );
  });

  it("maps legacy mission_control_userprofile to Admin", () => {
    assert.equal(
      getServiceLayer("mission_control_userprofile"),
      "Shifter Admin (management)"
    );
  });

  it("maps legacy mission_control_activitylog to Admin", () => {
    assert.equal(
      getServiceLayer("mission_control_activitylog"),
      "Shifter Admin (management)"
    );
  });

  it("returns Unknown for unrecognized tables", () => {
    assert.equal(getServiceLayer("some_random_table"), "Unknown");
  });

  it("legacy exact match takes priority over prefix match", () => {
    // If mission_control_ were in SERVICE_LAYERS, legacy should still win
    assert.notEqual(
      getServiceLayer("mission_control_range"),
      "Mission Control (presentation layer)"
    );
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

describe("FORBIDDEN_PATTERN", () => {
  const forbidden = [
    "DROP TABLE users",
    "DELETE FROM users",
    "UPDATE users SET name = 'x'",
    "INSERT INTO users VALUES (1)",
    "ALTER TABLE users ADD col int",
    "TRUNCATE users",
    "CREATE TABLE foo (id int)",
    "GRANT ALL ON users TO public",
    "REVOKE ALL ON users FROM public",
    "VACUUM users",
    "REINDEX TABLE users",
  ];

  for (const sql of forbidden) {
    it(`blocks: ${sql}`, () => {
      assert.ok(FORBIDDEN_PATTERN.test(sql));
    });
  }

  const allowed = [
    "SELECT * FROM users",
    "SELECT count(*) FROM deleted_records",
    "SELECT updated_at FROM users",
    "SELECT * FROM users WHERE created_at > NOW()",
    "EXPLAIN SELECT * FROM users",
    "SELECT insert_date FROM logs",
  ];

  for (const sql of allowed) {
    it(`allows: ${sql}`, () => {
      assert.ok(!FORBIDDEN_PATTERN.test(sql));
    });
  }

  it("is case-insensitive", () => {
    assert.ok(FORBIDDEN_PATTERN.test("drop table users"));
    assert.ok(FORBIDDEN_PATTERN.test("Drop Table Users"));
  });
});

describe("LOCAL_PORTS", () => {
  it("uses different ports for dev and prod", () => {
    assert.notEqual(LOCAL_PORTS.dev, LOCAL_PORTS.prod);
  });

  it("has dev on 15432", () => {
    assert.equal(LOCAL_PORTS.dev, 15432);
  });

  it("has prod on 15433", () => {
    assert.equal(LOCAL_PORTS.prod, 15433);
  });
});
