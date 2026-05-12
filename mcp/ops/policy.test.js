// Phase 1 tests — config parsing, class membership, profile gating,
// and registerTool wrapping. Integration-style: shared fixture,
// multiple assertions per test, no inline AsyncMock churn.
import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";
import {
  parsePolicy,
  loadPolicy,
  registerTool,
  PolicyError,
} from "./policy.js";
import { z } from "zod";

const BASE_POLICY = {
  version: 1,
  classes: [
    "observability",
    "named_db_read",
    "named_db_write",
    "secret_handle",
    "ssm_named",
    "ssm_arbitrary",
    "db_arbitrary",
    "infra_mutation",
    "dev_bypass_tunnel",
  ],
  session_profile: {
    default: "standard",
    profiles: {
      read_only: ["observability", "named_db_read"],
      standard: [
        "observability",
        "named_db_read",
        "named_db_write",
        "secret_handle",
        "ssm_named",
      ],
      destructive: [
        "observability",
        "named_db_read",
        "named_db_write",
        "secret_handle",
        "ssm_named",
        "ssm_arbitrary",
        "db_arbitrary",
        "infra_mutation",
        "dev_bypass_tunnel",
      ],
    },
  },
  environments: {
    default: "dev",
    prod_requires_confirm: true,
  },
  class_defaults: {
    observability: {},
    named_db_read: {},
    named_db_write: { idempotency_key: "required" },
    secret_handle: { return_mode: "handle" },
    ssm_named: {},
    ssm_arbitrary: { execute_default: false, two_phase: true },
    db_arbitrary: { execute_default: false, two_phase: true },
    infra_mutation: {
      execute_default: false,
      two_phase: true,
      rate_cap: { count: 3, window_seconds: 60 },
    },
    dev_bypass_tunnel: {
      allowed_envs: ["dev"],
      description_redaction: true,
    },
  },
  tools: {},
  audit: {
    enabled: true,
    // Synthetic path used only as Zod-shape input (no I/O happens
    // against this in tests). Kept off `/tmp/` so SonarCloud's S5443
    // hardcoded-tmp check stays clean.
    path: "./.test-audit.jsonl",
    redact: ["password"],
  },
};

function buildPolicy(overrides = {}, opts = {}) {
  const raw = { ...BASE_POLICY, ...overrides };
  return parsePolicy(raw, opts);
}

class FakeServer {
  constructor() {
    this.registered = [];
  }
  tool(name, description, schema, handler) {
    this.registered.push({ name, description, schema, handler });
  }
}

describe("parsePolicy", () => {
  it("resolves the default profile when none is supplied and exposes classes", () => {
    const p = buildPolicy();
    assert.equal(p.profile, "standard");
    assert.equal(p.classEnabled("observability"), true);
    assert.equal(p.classEnabled("named_db_write"), true);
    assert.equal(p.classEnabled("infra_mutation"), false);
    assert.equal(p.classEnabled("dev_bypass_tunnel"), false);
  });

  it("honors an explicit profile override", () => {
    const p = buildPolicy({}, { profile: "read_only" });
    assert.equal(p.profile, "read_only");
    assert.equal(p.classEnabled("observability"), true);
    assert.equal(p.classEnabled("named_db_read"), true);
    assert.equal(p.classEnabled("named_db_write"), false);
    assert.equal(p.classEnabled("secret_handle"), false);
  });

  it("enables every declared class under the destructive profile", () => {
    const p = buildPolicy({}, { profile: "destructive" });
    for (const klass of BASE_POLICY.classes) {
      assert.equal(p.classEnabled(klass), true, `class ${klass} should be enabled`);
    }
  });

  it("returns class defaults via classDefaults()", () => {
    const p = buildPolicy();
    assert.deepEqual(p.classDefaults("infra_mutation"), {
      execute_default: false,
      two_phase: true,
      rate_cap: { count: 3, window_seconds: 60 },
    });
    assert.deepEqual(p.classDefaults("secret_handle"), { return_mode: "handle" });
    assert.deepEqual(p.classDefaults("observability"), {});
  });

  it("fails closed on unknown profile", () => {
    assert.throws(
      () => buildPolicy({}, { profile: "godmode" }),
      PolicyError,
    );
  });

  it("fails closed on unknown class in a profile", () => {
    const bad = {
      ...BASE_POLICY,
      session_profile: {
        default: "weird",
        profiles: { weird: ["observability", "made_up_class"] },
      },
    };
    assert.throws(() => parsePolicy(bad), PolicyError);
  });

  it("fails closed on missing required top-level keys", () => {
    assert.throws(() => parsePolicy({}), PolicyError);
    assert.throws(() => parsePolicy({ version: 1 }), PolicyError);
  });

  it("rejects an unsupported policy version", () => {
    assert.throws(
      () => parsePolicy({ ...BASE_POLICY, version: 999 }),
      PolicyError,
    );
  });

  it("fails closed when a declared class is missing a class_defaults entry", () => {
    const partialDefaults = { ...BASE_POLICY.class_defaults };
    delete partialDefaults.observability;
    const bad = { ...BASE_POLICY, class_defaults: partialDefaults };
    assert.throws(() => parsePolicy(bad), PolicyError);
  });

  it("fails closed when a class_defaults entry is not an object", () => {
    const bad = {
      ...BASE_POLICY,
      class_defaults: { ...BASE_POLICY.class_defaults, observability: 42 },
    };
    assert.throws(() => parsePolicy(bad), PolicyError);
  });

  it("fails closed when class_defaults contains a key not declared in classes", () => {
    const bad = {
      ...BASE_POLICY,
      class_defaults: { ...BASE_POLICY.class_defaults, ghost: {} },
    };
    assert.throws(() => parsePolicy(bad), PolicyError);
  });

  it("fails closed on malformed environments shape", () => {
    // prod_requires_confirm as a string is the classic YAML typo
    // (`prod_requires_confirm: 'true'`) — must NOT silently parse to
    // false. Truthy-but-not-=== true would weaken the prod gate.
    assert.throws(
      () =>
        parsePolicy({
          ...BASE_POLICY,
          environments: { default: "dev", prod_requires_confirm: "true" },
        }),
      PolicyError,
    );
    // default env outside the dev/prod enum must fail closed.
    assert.throws(
      () =>
        parsePolicy({
          ...BASE_POLICY,
          environments: { default: "staging", prod_requires_confirm: true },
        }),
      PolicyError,
    );
    // missing prod_requires_confirm must fail closed.
    assert.throws(
      () =>
        parsePolicy({ ...BASE_POLICY, environments: { default: "dev" } }),
      PolicyError,
    );
  });

  it("fails closed on malformed audit shape", () => {
    assert.throws(
      () =>
        parsePolicy({
          ...BASE_POLICY,
          audit: { enabled: "yes", path: "./.a.jsonl", redact: [] },
        }),
      PolicyError,
    );
    assert.throws(
      () =>
        parsePolicy({
          ...BASE_POLICY,
          audit: { enabled: true, path: "", redact: [] },
        }),
      PolicyError,
    );
    assert.throws(
      () =>
        parsePolicy({
          ...BASE_POLICY,
          audit: { enabled: true, path: "./.a.jsonl", redact: "password" },
        }),
      PolicyError,
    );
  });

  it("fails closed on malformed class_defaults rate_cap or unknown keys", () => {
    // rate_cap.count must be a positive int
    assert.throws(
      () =>
        parsePolicy({
          ...BASE_POLICY,
          class_defaults: {
            ...BASE_POLICY.class_defaults,
            infra_mutation: { rate_cap: { count: "three", window_seconds: 60 } },
          },
        }),
      PolicyError,
    );
    // Unknown key inside a class_defaults entry must fail (strict)
    assert.throws(
      () =>
        parsePolicy({
          ...BASE_POLICY,
          class_defaults: {
            ...BASE_POLICY.class_defaults,
            observability: { unknown_field: true },
          },
        }),
      PolicyError,
    );
    // allowed_envs must be a non-empty array of dev|prod
    assert.throws(
      () =>
        parsePolicy({
          ...BASE_POLICY,
          class_defaults: {
            ...BASE_POLICY.class_defaults,
            dev_bypass_tunnel: { allowed_envs: ["staging"], description_redaction: true },
          },
        }),
      PolicyError,
    );
  });

  it("fails closed on tools.<name> with an undeclared class", () => {
    assert.throws(
      () =>
        parsePolicy({
          ...BASE_POLICY,
          tools: { weird_tool: { class: "ghost_class" } },
        }),
      PolicyError,
    );
  });

  it("fails closed on tools.<name>.overrides with malformed shape", () => {
    assert.throws(
      () =>
        parsePolicy({
          ...BASE_POLICY,
          tools: {
            "foo": { overrides: { rate_cap: { count: 0, window_seconds: 60 } } },
          },
        }),
      PolicyError,
    );
  });

  it("rejects tools.<name>.class — class is descriptor-only, not config", () => {
    // Per cycle-3 codex finding: tools.<name>.class would create two
    // competing sources of truth for capability class. Schema drops it.
    assert.throws(
      () =>
        parsePolicy({
          ...BASE_POLICY,
          tools: { list_things: { class: "observability" } },
        }),
      PolicyError,
    );
  });

  describe("ADR-014-R5 semantic invariants", () => {
    it("rejects infra_mutation with execute_default: true", () => {
      const bad = {
        ...BASE_POLICY,
        class_defaults: {
          ...BASE_POLICY.class_defaults,
          infra_mutation: {
            execute_default: true,
            two_phase: true,
            rate_cap: { count: 3, window_seconds: 60 },
          },
        },
      };
      assert.throws(() => parsePolicy(bad), PolicyError);
    });

    it("rejects ssm_arbitrary without two_phase", () => {
      const bad = {
        ...BASE_POLICY,
        class_defaults: {
          ...BASE_POLICY.class_defaults,
          ssm_arbitrary: { execute_default: false },
        },
      };
      assert.throws(() => parsePolicy(bad), PolicyError);
    });

    it("rejects db_arbitrary with two_phase: false", () => {
      const bad = {
        ...BASE_POLICY,
        class_defaults: {
          ...BASE_POLICY.class_defaults,
          db_arbitrary: { execute_default: false, two_phase: false },
        },
      };
      assert.throws(() => parsePolicy(bad), PolicyError);
    });

    it("rejects named_db_write without idempotency_key=required", () => {
      const bad = {
        ...BASE_POLICY,
        class_defaults: {
          ...BASE_POLICY.class_defaults,
          named_db_write: { idempotency_key: "optional" },
        },
      };
      assert.throws(() => parsePolicy(bad), PolicyError);
    });

    it("rejects secret_handle with return_mode: value", () => {
      const bad = {
        ...BASE_POLICY,
        class_defaults: {
          ...BASE_POLICY.class_defaults,
          secret_handle: { return_mode: "value" },
        },
      };
      assert.throws(() => parsePolicy(bad), PolicyError);
    });

    it("rejects dev_bypass_tunnel with allowed_envs including prod", () => {
      const bad = {
        ...BASE_POLICY,
        class_defaults: {
          ...BASE_POLICY.class_defaults,
          dev_bypass_tunnel: {
            allowed_envs: ["dev", "prod"],
            description_redaction: true,
          },
        },
      };
      assert.throws(() => parsePolicy(bad), PolicyError);
    });

    it("rejects dev_bypass_tunnel without description_redaction", () => {
      const bad = {
        ...BASE_POLICY,
        class_defaults: {
          ...BASE_POLICY.class_defaults,
          dev_bypass_tunnel: { allowed_envs: ["dev"] },
        },
      };
      assert.throws(() => parsePolicy(bad), PolicyError);
    });

    it("rejects environments.prod_requires_confirm: false", () => {
      const bad = {
        ...BASE_POLICY,
        environments: { default: "dev", prod_requires_confirm: false },
      };
      assert.throws(() => parsePolicy(bad), PolicyError);
    });

    it("rejects audit.enabled: false", () => {
      const bad = {
        ...BASE_POLICY,
        audit: { enabled: false, path: "./.x.jsonl", redact: [] },
      };
      assert.throws(() => parsePolicy(bad), PolicyError);
    });

    it("accepts a policy that declares classes outside the ADR-014 set without invariants", () => {
      // A future class added to .shifter.yaml (not in the ADR-014
      // invariant table) parses cleanly without semantic checks
      // applied. Bumping ADR-014 adds the new class's invariants.
      const future = {
        ...BASE_POLICY,
        classes: [...BASE_POLICY.classes, "future_class"],
        class_defaults: {
          ...BASE_POLICY.class_defaults,
          future_class: {},
        },
        session_profile: {
          default: "standard",
          profiles: {
            ...BASE_POLICY.session_profile.profiles,
            standard: [
              ...BASE_POLICY.session_profile.profiles.standard,
              "future_class",
            ],
          },
        },
      };
      const p = parsePolicy(future);
      assert.equal(p.classEnabled("future_class"), true);
    });
  });
});

describe("loadPolicy", () => {
  it("reads .shifter.yaml from a given path and returns a Policy", async () => {
    const { writeFileSync, mkdtempSync } = await import("node:fs");
    const os = await import("node:os");
    const path = await import("node:path");
    const dir = mkdtempSync(path.join(os.tmpdir(), "policy-load-"));
    const file = path.join(dir, ".shifter.yaml");
    writeFileSync(
      file,
      `mcp_ops:\n  version: 1\n  classes: [observability]\n  session_profile:\n    default: read_only\n    profiles:\n      read_only: [observability]\n  environments:\n    default: dev\n    prod_requires_confirm: true\n  class_defaults:\n    observability: {}\n  tools: {}\n  audit:\n    enabled: true\n    path: ./.x.jsonl\n    redact: []\n`,
    );
    const p = loadPolicy({ path: file });
    assert.equal(p.profile, "read_only");
    assert.equal(p.classEnabled("observability"), true);
  });

  it("loads the repo-root .shifter.yaml and resolves every declared class", async () => {
    const path = await import("node:path");
    const url = await import("node:url");
    const here = path.dirname(url.fileURLToPath(import.meta.url));
    const repoRoot = path.resolve(here, "..", "..");
    const file = path.join(repoRoot, ".shifter.yaml");
    const p = loadPolicy({ path: file });
    // Default profile from the real file is `standard` — the
    // declared classes must be a strict superset of the active ones.
    assert.equal(p.profile, "standard");
    assert.equal(p.classEnabled("observability"), true);
    assert.equal(p.classEnabled("named_db_read"), true);
    assert.equal(p.classEnabled("named_db_write"), true);
    assert.equal(p.classEnabled("secret_handle"), true);
    assert.equal(p.classEnabled("ssm_named"), true);
    // Destructive classes are NOT in the standard profile.
    assert.equal(p.classEnabled("infra_mutation"), false);
    assert.equal(p.classEnabled("db_arbitrary"), false);
    assert.equal(p.classEnabled("ssm_arbitrary"), false);
    assert.equal(p.classEnabled("dev_bypass_tunnel"), false);
    // Every class has a class_defaults entry (even if empty).
    for (const klass of [
      "observability",
      "named_db_read",
      "named_db_write",
      "secret_handle",
      "ssm_named",
      "ssm_arbitrary",
      "db_arbitrary",
      "infra_mutation",
      "dev_bypass_tunnel",
    ]) {
      assert.equal(p.classDeclared(klass), true, `class ${klass} should be declared`);
      const defaults = p.classDefaults(klass);
      assert.equal(typeof defaults, "object", `class ${klass} should have defaults`);
    }
    assert.equal(p.envDefault(), "dev");
    assert.equal(p.envProdRequiresConfirm(), true);
  });

  it("honors SHIFTER_OPS_PROFILE override via the explicit profile argument", async () => {
    const path = await import("node:path");
    const url = await import("node:url");
    const here = path.dirname(url.fileURLToPath(import.meta.url));
    const repoRoot = path.resolve(here, "..", "..");
    const file = path.join(repoRoot, ".shifter.yaml");
    const p = loadPolicy({ path: file, profile: "destructive" });
    assert.equal(p.profile, "destructive");
    assert.equal(p.classEnabled("infra_mutation"), true);
    assert.equal(p.classEnabled("db_arbitrary"), true);
    assert.equal(p.classEnabled("ssm_arbitrary"), true);
    assert.equal(p.classEnabled("dev_bypass_tunnel"), true);
  });
});

describe("registerTool", () => {
  let server;
  let audit;
  beforeEach(() => {
    server = new FakeServer();
    audit = { records: [], append: function (r) { this.records.push(r); } };
  });

  it("registers an observability tool under the standard profile", () => {
    const policy = buildPolicy();
    registerTool(
      { server, policy, audit },
      {
        name: "list_things",
        klass: "observability",
        description: "List things",
        schema: { env: z.enum(["dev", "prod"]).default("dev") },
        handler: async () => ({ content: [{ type: "text", text: "ok" }] }),
      },
    );
    assert.equal(server.registered.length, 1);
    assert.equal(server.registered[0].name, "list_things");
    assert.equal(server.registered[0].description, "List things");
  });

  it("does NOT register tools whose class is disabled by the active profile", () => {
    const policy = buildPolicy({}, { profile: "read_only" });
    registerTool(
      { server, policy, audit },
      {
        name: "terminate_thing",
        klass: "infra_mutation",
        description: "Terminate",
        schema: { id: z.string() },
        handler: async () => ({ content: [] }),
      },
    );
    registerTool(
      { server, policy, audit },
      {
        name: "list_things",
        klass: "observability",
        description: "List",
        schema: {},
        handler: async () => ({ content: [] }),
      },
    );
    assert.equal(server.registered.length, 1);
    assert.equal(server.registered[0].name, "list_things");
  });

  it("rejects a descriptor without a class", () => {
    const policy = buildPolicy();
    assert.throws(
      () =>
        registerTool(
          { server, policy, audit },
          {
            name: "no_class",
            description: "",
            schema: {},
            handler: async () => ({ content: [] }),
          },
        ),
      PolicyError,
    );
  });

  it("rejects a descriptor whose class is not declared in the policy", () => {
    const policy = buildPolicy();
    assert.throws(
      () =>
        registerTool(
          { server, policy, audit },
          {
            name: "weird",
            klass: "made_up_class",
            description: "",
            schema: {},
            handler: async () => ({ content: [] }),
          },
        ),
      PolicyError,
    );
  });
});
