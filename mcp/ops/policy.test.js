// Phase 1 tests — config parsing, class membership, profile gating,
// and registerTool wrapping. Integration-style: shared fixture,
// multiple assertions per test, no inline AsyncMock churn.
import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  parsePolicy,
  loadPolicy,
  registerTool,
  PolicyError,
  resolveSecretHandle,
  _resetGateCachesForTests,
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

// ===========================================================================
// Phase 2 gates (#1198)
//
// Each describe block here covers one gate. The gates compose around
// the handler at `registerTool` time; the tests invoke the wrapped
// handler captured in the FakeServer and assert on what it produces.
//
// All gate tests disable the audit append (`audit.enabled: false`) so
// they do not write to disk. A separate `describe("audit append")`
// block builds a policy with a tmpdir audit path and asserts on the
// emitted JSONL.
// ===========================================================================

// ADR-014-R5 requires `audit.enabled: true` at parse time, so tests
// cannot simply disable it. Instead, route audit writes to a single
// per-test tmpdir path that we delete in afterAll. Tests that care
// about audit contents use their own buildAuditPolicy below; tests
// that only care about gate behavior just point the writer at /dev/null-ish.
const _SHARED_AUDIT_DIR = mkdtempSync(join(tmpdir(), "policy-gates-test-"));
const _SHARED_AUDIT_PATH = join(_SHARED_AUDIT_DIR, "noise.jsonl");

function buildPolicyAuditOff(extraOverrides = {}, opts = {}) {
  const merged = {
    ...BASE_POLICY,
    audit: { enabled: true, path: _SHARED_AUDIT_PATH, redact: [] },
    ...extraOverrides,
  };
  return parsePolicy(merged, opts);
}

async function callRegisteredTool(server, toolName, args) {
  const found = server.registered.find((r) => r.name === toolName);
  if (!found) throw new Error(`tool ${toolName} not registered`);
  return found.handler(args);
}

describe("registerTool gates (Phase 2): env policy", () => {
  let server;
  beforeEach(() => {
    server = new FakeServer();
    _resetGateCachesForTests();
  });

  it("refuses prod calls without confirm_env=prod for prod-touching classes", async () => {
    const policy = buildPolicyAuditOff({}, { profile: "destructive" });
    let handlerCalled = false;
    registerTool(
      { server, policy },
      {
        name: "terminate_ec2",
        klass: "infra_mutation",
        description: "",
        schema: {},
        handler: async () => {
          handlerCalled = true;
          return { content: [] };
        },
      },
    );
    await assert.rejects(
      callRegisteredTool(server, "terminate_ec2", { env: "prod", execute: true }),
      (e) => e instanceof PolicyError && /confirm_env="prod"/.test(e.message),
    );
    assert.equal(handlerCalled, false, "handler must not run when env gate fails");
  });

  it("accepts prod calls when confirm_env=prod is supplied", async () => {
    const policy = buildPolicyAuditOff({}, { profile: "destructive" });
    registerTool(
      { server, policy },
      {
        name: "terminate_ec2",
        klass: "infra_mutation",
        description: "",
        schema: {},
        handler: async () => ({ content: [{ type: "text", text: "ok" }] }),
      },
    );
    const res = await callRegisteredTool(server, "terminate_ec2", {
      env: "prod",
      confirm_env: "prod",
      execute: true,
    });
    assert.equal(res.content[0].text, "ok");
  });

  it("non-prod calls are unaffected by the confirm gate", async () => {
    const policy = buildPolicyAuditOff();
    registerTool(
      { server, policy },
      {
        name: "list_db",
        klass: "named_db_read",
        description: "",
        schema: {},
        handler: async () => ({ content: [{ type: "text", text: "ok" }] }),
      },
    );
    const res = await callRegisteredTool(server, "list_db", { env: "dev" });
    assert.equal(res.content[0].text, "ok");
  });

  it("dev_bypass_tunnel refuses env outside its allowed_envs list", async () => {
    const policy = buildPolicyAuditOff({}, { profile: "destructive" });
    registerTool(
      { server, policy },
      {
        name: "start_portal_test_tunnel",
        klass: "dev_bypass_tunnel",
        description: "",
        schema: {},
        handler: async () => ({ content: [] }),
      },
    );
    await assert.rejects(
      callRegisteredTool(server, "start_portal_test_tunnel", {
        env: "prod",
        confirm_env: "prod",
      }),
      (e) => e instanceof PolicyError && /allowed_envs/.test(e.message),
    );
  });
});

describe("registerTool gates (Phase 2): dry-run defaults", () => {
  let server;
  beforeEach(() => {
    server = new FakeServer();
    _resetGateCachesForTests();
  });

  it("returns a preview without invoking the handler when execute is missing", async () => {
    const policy = buildPolicyAuditOff({}, { profile: "destructive" });
    let handlerCalled = false;
    registerTool(
      { server, policy },
      {
        name: "query",
        klass: "db_arbitrary",
        description: "",
        schema: {},
        handler: async () => {
          handlerCalled = true;
          return { content: [{ type: "text", text: "should not run" }] };
        },
      },
    );
    const res = await callRegisteredTool(server, "query", { env: "dev", sql: "select 1" });
    assert.equal(handlerCalled, false);
    const parsed = JSON.parse(res.content[0].text);
    assert.equal(parsed.dry_run, true);
    assert.equal(parsed.tool, "query");
    assert.deepEqual(parsed.would_execute_with, { env: "dev", sql: "select 1" });
  });

  it("runs the handler when execute=true is supplied", async () => {
    const policy = buildPolicyAuditOff({}, { profile: "destructive" });
    let handlerCalled = false;
    registerTool(
      { server, policy },
      {
        name: "query",
        klass: "db_arbitrary",
        description: "",
        schema: {},
        handler: async () => {
          handlerCalled = true;
          return { content: [{ type: "text", text: "real result" }] };
        },
      },
    );
    const res = await callRegisteredTool(server, "query", { env: "dev", execute: true, sql: "select 1" });
    assert.equal(handlerCalled, true);
    assert.equal(res.content[0].text, "real result");
  });

  it("classes without execute_default:false skip dry-run entirely", async () => {
    const policy = buildPolicyAuditOff();
    registerTool(
      { server, policy },
      {
        name: "list_logs",
        klass: "observability",
        description: "",
        schema: {},
        handler: async () => ({ content: [{ type: "text", text: "logs" }] }),
      },
    );
    const res = await callRegisteredTool(server, "list_logs", { env: "dev" });
    assert.equal(res.content[0].text, "logs");
  });
});

describe("registerTool gates (Phase 2): description redaction", () => {
  let server;
  beforeEach(() => {
    server = new FakeServer();
    _resetGateCachesForTests();
  });

  it("replaces dev_bypass_tunnel descriptions before reaching server.tool()", () => {
    const policy = buildPolicyAuditOff({}, { profile: "destructive" });
    registerTool(
      { server, policy },
      {
        name: "start_portal_test_tunnel",
        klass: "dev_bypass_tunnel",
        description: "Use the SSM port-forward bypass to skip MFA and reach the dev portal directly.",
        schema: {},
        handler: async () => ({ content: [] }),
      },
    );
    const registered = server.registered.find((r) => r.name === "start_portal_test_tunnel");
    assert.equal(registered.description, "[description redacted per ADR-014-R6 — operator agent tool]");
    assert.equal(registered.description.includes("SSM"), false);
    assert.equal(registered.description.includes("bypass"), false);
    assert.equal(registered.description.includes("MFA"), false);
  });

  it("does not redact descriptions for non-bypass classes", () => {
    const policy = buildPolicyAuditOff();
    registerTool(
      { server, policy },
      {
        name: "list_things",
        klass: "observability",
        description: "List logs.",
        schema: {},
        handler: async () => ({ content: [] }),
      },
    );
    assert.equal(server.registered[0].description, "List logs.");
  });
});

describe("registerTool gates (Phase 2): idempotency keys", () => {
  let server;
  beforeEach(() => {
    server = new FakeServer();
    _resetGateCachesForTests();
  });

  it("refuses named_db_write calls without an idempotency_key", async () => {
    const policy = buildPolicyAuditOff();
    registerTool(
      { server, policy },
      {
        name: "create_risk",
        klass: "named_db_write",
        description: "",
        schema: {},
        handler: async () => ({ content: [{ type: "text", text: "ok" }] }),
      },
    );
    await assert.rejects(
      callRegisteredTool(server, "create_risk", { title: "x" }),
      (e) => e instanceof PolicyError && /idempotency_key/.test(e.message),
    );
  });

  it("returns the cached result on retry with the same key", async () => {
    const policy = buildPolicyAuditOff();
    let runCount = 0;
    registerTool(
      { server, policy },
      {
        name: "create_risk",
        klass: "named_db_write",
        description: "",
        schema: {},
        handler: async () => {
          runCount += 1;
          return { content: [{ type: "text", text: `result-${runCount}` }] };
        },
      },
    );
    const first = await callRegisteredTool(server, "create_risk", {
      title: "x",
      idempotency_key: "abc",
    });
    const second = await callRegisteredTool(server, "create_risk", {
      title: "x",
      idempotency_key: "abc",
    });
    assert.equal(first.content[0].text, "result-1");
    assert.equal(second.content[0].text, "result-1", "cached result must be returned");
    assert.equal(runCount, 1, "handler must run exactly once across the retries");
  });

  it("different idempotency keys execute the handler independently", async () => {
    const policy = buildPolicyAuditOff();
    let runCount = 0;
    registerTool(
      { server, policy },
      {
        name: "create_risk",
        klass: "named_db_write",
        description: "",
        schema: {},
        handler: async () => {
          runCount += 1;
          return { content: [{ type: "text", text: `result-${runCount}` }] };
        },
      },
    );
    const a = await callRegisteredTool(server, "create_risk", { idempotency_key: "k1" });
    const b = await callRegisteredTool(server, "create_risk", { idempotency_key: "k2" });
    assert.equal(a.content[0].text, "result-1");
    assert.equal(b.content[0].text, "result-2");
    assert.equal(runCount, 2);
  });

  it("same key with different args is REFUSED as a programming error", async () => {
    // Codex review #1180 cycle 2 finding 1: reusing an
    // idempotency_key with different non-control args is a
    // programming error; the wrapper must refuse the second call
    // rather than executing it as a fresh write OR returning the
    // stale cached result.
    const policy = buildPolicyAuditOff();
    let runCount = 0;
    registerTool(
      { server, policy },
      {
        name: "create_risk",
        klass: "named_db_write",
        description: "",
        schema: {},
        handler: async (args) => {
          runCount += 1;
          return { content: [{ type: "text", text: `${runCount}:${args.title}` }] };
        },
      },
    );
    const a = await callRegisteredTool(server, "create_risk", {
      idempotency_key: "k1",
      title: "alpha",
    });
    await assert.rejects(
      callRegisteredTool(server, "create_risk", {
        idempotency_key: "k1",
        title: "beta",
      }),
      (e) => e instanceof PolicyError && /different args/.test(e.message),
    );
    assert.equal(a.content[0].text, "1:alpha");
    assert.equal(runCount, 1, "handler must not run again for the mismatched retry");
  });

  it("expired idempotency entries are reaped (TTL eviction)", async () => {
    // Codex review #1180 cycle 2 finding 2: a long-lived server
    // must not accumulate one cached entry per unique key forever.
    const policy = buildPolicyAuditOff();
    let runCount = 0;
    registerTool(
      { server, policy },
      {
        name: "create_risk",
        klass: "named_db_write",
        description: "",
        schema: {},
        handler: async () => {
          runCount += 1;
          return { content: [{ type: "text", text: `r-${runCount}` }] };
        },
      },
    );
    const a = await callRegisteredTool(server, "create_risk", { idempotency_key: "k-evict" });
    assert.equal(a.content[0].text, "r-1");

    const realNow = Date.now;
    try {
      // Travel past the 15-minute TTL.
      const future = realNow() + 16 * 60 * 1000;
      Date.now = () => future;
      // A fresh call with a DIFFERENT key triggers the reap; after
      // it, the original key's entry is gone (TTL exceeded).
      const b = await callRegisteredTool(server, "create_risk", { idempotency_key: "k-new" });
      assert.equal(b.content[0].text, "r-2");

      // Re-using "k-evict" with the SAME args after reap should run
      // fresh (it was evicted), proving the cache was swept.
      const c = await callRegisteredTool(server, "create_risk", { idempotency_key: "k-evict" });
      assert.equal(c.content[0].text, "r-3");
    } finally {
      Date.now = realNow;
    }
  });

  it("concurrent retries with the same key but different args are REFUSED", async () => {
    // Codex review #1180 cycle 3 finding 1: the in-flight path must
    // validate fingerprints, not just the cacheKey. A concurrent
    // retry with mismatched payload is the same programming error
    // as the serial mismatched-retry case (cycle 2 finding 1) and
    // must be refused with the same error.
    const policy = buildPolicyAuditOff();
    let runCount = 0;
    let resolveHandler;
    const handlerStarted = new Promise((r) => (resolveHandler = r));
    registerTool(
      { server, policy },
      {
        name: "create_risk",
        klass: "named_db_write",
        description: "",
        schema: {},
        handler: async (args) => {
          runCount += 1;
          resolveHandler();
          await new Promise((r) => setTimeout(r, 30));
          return { content: [{ type: "text", text: `r-${runCount}:${args.title}` }] };
        },
      },
    );

    const first = callRegisteredTool(server, "create_risk", {
      idempotency_key: "k1",
      title: "alpha",
    });
    await handlerStarted;
    await assert.rejects(
      callRegisteredTool(server, "create_risk", {
        idempotency_key: "k1",
        title: "beta", // different fingerprint
      }),
      (e) => e instanceof PolicyError && /different args/.test(e.message),
    );
    const a = await first;
    assert.equal(a.content[0].text, "r-1:alpha");
    assert.equal(runCount, 1);
  });

  it("concurrent retries with the same key share one execution", async () => {
    // Codex review #1180 cycle 1 finding 4: the in-flight Promise
    // map ensures two retries arriving within the handler's window
    // do not both execute. Both await the same Promise; the handler
    // runs exactly once.
    const policy = buildPolicyAuditOff();
    let runCount = 0;
    let resolveHandler;
    const handlerStarted = new Promise((r) => (resolveHandler = r));
    registerTool(
      { server, policy },
      {
        name: "create_risk",
        klass: "named_db_write",
        description: "",
        schema: {},
        handler: async () => {
          runCount += 1;
          resolveHandler();
          // Hold the handler open long enough for the second call
          // to find the in-flight Promise.
          await new Promise((r) => setTimeout(r, 30));
          return { content: [{ type: "text", text: `result-${runCount}` }] };
        },
      },
    );

    const first = callRegisteredTool(server, "create_risk", { idempotency_key: "k1" });
    // Wait until the handler is in flight before issuing the retry.
    await handlerStarted;
    const second = callRegisteredTool(server, "create_risk", { idempotency_key: "k1" });

    const [a, b] = await Promise.all([first, second]);
    assert.equal(a.content[0].text, "result-1");
    assert.equal(b.content[0].text, "result-1");
    assert.equal(runCount, 1, "handler must execute exactly once across concurrent retries");
  });
});

describe("registerTool gates (Phase 2): per-tool overrides", () => {
  let server;
  beforeEach(() => {
    server = new FakeServer();
    _resetGateCachesForTests();
  });

  it("per-tool overrides relax dry-run defaults when configured", async () => {
    // Codex review #1180 cycle 1 finding 3: gates must consume the
    // resolved tool policy. Build a policy where `query`
    // specifically opts out of dry-run via tools.<name>.overrides.
    const policy = parsePolicy(
      {
        ...BASE_POLICY,
        audit: { enabled: true, path: _SHARED_AUDIT_PATH, redact: [] },
        tools: {
          query: {
            overrides: { execute_default: true },
          },
        },
      },
      { profile: "destructive" },
    );
    let handlerCalled = false;
    registerTool(
      { server, policy },
      {
        name: "query",
        klass: "db_arbitrary",
        description: "",
        schema: {},
        handler: async () => {
          handlerCalled = true;
          return { content: [{ type: "text", text: "real" }] };
        },
      },
    );
    // Without execute=true, class default would dry-run. Tool
    // override flips execute_default to true, so the handler runs.
    const res = await callRegisteredTool(server, "query", { env: "dev", sql: "select 1" });
    assert.equal(handlerCalled, true);
    assert.equal(res.content[0].text, "real");
  });

  it("per-tool overrides can require idempotency on a class that does not by default", async () => {
    const policy = parsePolicy(
      {
        ...BASE_POLICY,
        audit: { enabled: true, path: _SHARED_AUDIT_PATH, redact: [] },
        tools: {
          touchy_read: {
            overrides: { idempotency_key: "required" },
          },
        },
      },
      {},
    );
    registerTool(
      { server, policy },
      {
        name: "touchy_read",
        klass: "named_db_read",
        description: "",
        schema: {},
        handler: async () => ({ content: [{ type: "text", text: "ok" }] }),
      },
    );
    await assert.rejects(
      callRegisteredTool(server, "touchy_read", {}),
      (e) => e instanceof PolicyError && /idempotency_key/.test(e.message),
    );
  });
});

describe("registerTool gates (Phase 2): secret handles", () => {
  let server;
  beforeEach(() => {
    server = new FakeServer();
    _resetGateCachesForTests();
  });

  it("wraps secret_handle return values into shf-secret:<uuid> handles", async () => {
    const policy = buildPolicyAuditOff();
    registerTool(
      { server, policy },
      {
        name: "get_secret",
        klass: "secret_handle",
        description: "",
        schema: {},
        handler: async () => ({ content: [{ type: "text", text: "raw-db-password" }] }),
      },
    );
    const res = await callRegisteredTool(server, "get_secret", { secret_id: "x" });
    const text = res.content[0].text;
    assert.ok(text.startsWith("shf-secret:"), `got: ${text}`);
    assert.notEqual(text, "raw-db-password", "raw value must not be returned");
    // resolveSecretHandle gives the raw value back in-process.
    assert.equal(resolveSecretHandle(text), "raw-db-password");
  });

  it("resolveSecretHandle throws on an unknown handle", () => {
    assert.throws(
      () => resolveSecretHandle("shf-secret:00000000-0000-0000-0000-000000000000"),
      (e) => e instanceof PolicyError && /unknown handle/.test(e.message),
    );
  });

  it("resolveSecretHandle drops expired handles and refuses to return their value", async () => {
    const policy = buildPolicyAuditOff();
    registerTool(
      { server, policy },
      {
        name: "get_secret",
        klass: "secret_handle",
        description: "",
        schema: {},
        handler: async () => ({ content: [{ type: "text", text: "raw-value" }] }),
      },
    );
    const res = await callRegisteredTool(server, "get_secret", {});
    const handle = res.content[0].text;

    // First resolve within TTL succeeds.
    assert.equal(resolveSecretHandle(handle), "raw-value");

    // Travel past the 15-minute TTL by overwriting Date.now. The
    // module reads Date.now() inside resolveSecretHandle; we patch
    // and restore in a try/finally.
    const realNow = Date.now;
    try {
      const future = realNow() + 16 * 60 * 1000;
      Date.now = () => future;
      assert.throws(
        () => resolveSecretHandle(handle),
        (e) => e instanceof PolicyError && /expired/.test(e.message),
      );
      // Expired handle was also dropped from the map.
      assert.throws(
        () => resolveSecretHandle(handle),
        (e) => e instanceof PolicyError && /unknown handle/.test(e.message),
      );
    } finally {
      Date.now = realNow;
    }
  });

  it("non-secret-handle classes pass results through unchanged", async () => {
    const policy = buildPolicyAuditOff();
    registerTool(
      { server, policy },
      {
        name: "list_things",
        klass: "observability",
        description: "",
        schema: {},
        handler: async () => ({ content: [{ type: "text", text: "raw-info" }] }),
      },
    );
    const res = await callRegisteredTool(server, "list_things", {});
    assert.equal(res.content[0].text, "raw-info");
  });
});

describe("registerTool gates (Phase 2): audit append", () => {
  let server;
  let tmpDir;
  let auditPath;
  beforeEach(() => {
    server = new FakeServer();
    _resetGateCachesForTests();
    tmpDir = mkdtempSync(join(tmpdir(), "policy-audit-test-"));
    auditPath = join(tmpDir, "audit.jsonl");
  });
  afterEach(() => {
    try {
      rmSync(tmpDir, { recursive: true, force: true });
    } catch {
      // best-effort
    }
  });

  function buildAuditPolicy(opts = {}) {
    return parsePolicy(
      {
        ...BASE_POLICY,
        audit: {
          enabled: true,
          path: auditPath,
          redact: ["password", "db_password"],
        },
      },
      opts,
    );
  }

  it("appends one JSONL line per call with sanitized args", async () => {
    const policy = buildAuditPolicy();
    registerTool(
      { server, policy },
      {
        name: "list_things",
        klass: "observability",
        description: "",
        schema: {},
        handler: async () => ({ content: [{ type: "text", text: "ok" }] }),
      },
    );
    await callRegisteredTool(server, "list_things", { env: "dev", password: "leaked" });
    await callRegisteredTool(server, "list_things", { env: "dev" });

    assert.ok(existsSync(auditPath));
    const lines = readFileSync(auditPath, "utf-8").trim().split("\n");
    assert.equal(lines.length, 2);
    const r1 = JSON.parse(lines[0]);
    assert.equal(r1.tool, "list_things");
    assert.equal(r1.class, "observability");
    assert.equal(r1.env, "dev");
    assert.equal(r1.profile, "standard");
    assert.equal(r1.sanitized_args.password, "<redacted>");
    assert.equal(r1.result_class, "success");
    assert.equal(typeof r1.duration_ms, "number");
  });

  it("records dry_run results, then success on a real execute", async () => {
    const policy = parsePolicy(
      {
        ...BASE_POLICY,
        audit: { enabled: true, path: auditPath, redact: [] },
      },
      { profile: "destructive" },
    );
    registerTool(
      { server, policy },
      {
        name: "query",
        klass: "db_arbitrary",
        description: "",
        schema: {},
        handler: async () => ({ content: [{ type: "text", text: "ok" }] }),
      },
    );
    await callRegisteredTool(server, "query", { env: "dev", sql: "select 1" });
    await callRegisteredTool(server, "query", { env: "dev", execute: true, sql: "select 1" });
    const lines = readFileSync(auditPath, "utf-8").trim().split("\n");
    assert.equal(lines.length, 2);
    assert.equal(JSON.parse(lines[0]).result_class, "dry_run");
    assert.equal(JSON.parse(lines[1]).result_class, "success");
  });

  it("records error result_class when the handler throws", async () => {
    const policy = buildAuditPolicy();
    registerTool(
      { server, policy },
      {
        name: "list_things",
        klass: "observability",
        description: "",
        schema: {},
        handler: async () => {
          throw new Error("boom");
        },
      },
    );
    await assert.rejects(callRegisteredTool(server, "list_things", { env: "dev" }));
    const line = JSON.parse(readFileSync(auditPath, "utf-8").trim());
    assert.equal(line.result_class, "error");
    assert.equal(line.error_class, "Error");
  });
});
