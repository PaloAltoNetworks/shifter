// ADR-014-R3 / R5 / R6 negative-surface tests for the mcp/ops MCP
// server. The contract here is "exercise the live registration seam
// the way an MCP client sees it": instantiate a FakeServer, load the
// real `.shifter.yaml` via `loadPolicy`, register the real `mcp/ops`
// descriptors through the real `registerTool`, then inspect the
// resulting tool set, descriptions, schemas, and wrapped handlers.
//
// The test deliberately does NOT parse `index.js` as text or copy
// private policy helpers — that would let a future refactor silently
// diverge the test from the live behavior. The expected surface is
// hardcoded per profile so adding or removing a tool requires updating
// EXPECTED_<PROFILE> in this file (the same maintenance contract as
// `mcp/ngfw/tool-surface.test.js`).
//
// See `docs/architecture/mcp-ops-privileged-surface-preflight-777.md`
// § "Phase 6 Preflight (#1202)" for the architecture rationale.

import { after, before, describe, it } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import yaml from "yaml";

import {
  loadPolicy,
  PolicyError,
  consumeApexToken,
  _resetGateCachesForTests,
} from "./policy.js";
import { registerAllOpsTools } from "./index.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const LIVE_POLICY_PATH = path.join(REPO_ROOT, ".shifter.yaml");

// Codex review #1202 cycle 2 finding 1 (class) and cycle 3 finding 1
// (one-off): the wrapped handlers the surface tests invoke all call
// `appendAuditRecord` — including refusal paths — and the LIVE
// `.shifter.yaml`'s `audit.path` points at `~/.shifter-ops-audit.jsonl`.
// Running the test against that path would (a) make the suite
// non-hermetic and (b) inject synthetic entries into the operator's
// real ops audit history. The fix preserves the "real `.shifter.yaml`
// through loadPolicy" contract by reading the live file, parsing it,
// overriding ONLY `mcp_ops.audit.path` to a per-process temp file,
// re-serializing it as YAML to a temp file, and then calling the real
// `loadPolicy({path, profile})` against the temp file. This exercises
// the same startup path `main()` uses; if `loadPolicy` later changes
// config discovery / namespace extraction / startup failure behavior,
// the surface suite is still covering it.
let TMP_DIR = null;
let TMP_AUDIT_PATH = null;
let TMP_POLICY_PATH = null;

before(() => {
  // Hold the temp dir under the test file's parent (not /tmp) to
  // sidestep SonarCloud S5443 and keep the path predictable for
  // post-mortem inspection if a test ever fails.
  TMP_DIR = mkdtempSync(path.join(__dirname, ".surface-test-"));
  TMP_AUDIT_PATH = path.join(TMP_DIR, "audit.jsonl");
  TMP_POLICY_PATH = path.join(TMP_DIR, "shifter.yaml");
  const doc = yaml.parse(readFileSync(LIVE_POLICY_PATH, "utf-8"));
  doc.mcp_ops.audit.path = TMP_AUDIT_PATH;
  writeFileSync(TMP_POLICY_PATH, yaml.stringify(doc));
});

after(() => {
  if (TMP_DIR) {
    rmSync(TMP_DIR, { recursive: true, force: true });
  }
});

// The redacted-description constant lives in `policy.js` and is the
// strict equality target asserted by the dev_bypass_tunnel test below.
// Asserting equality (rather than "does not contain /dev-login/") is
// the stronger invariant: it proves the entire raw description was
// replaced, not phrase-stripped.
const REDACTED_DESCRIPTION =
  "[description redacted per ADR-014-R6 — operator agent tool]";

// FakeServer mirrors the SDK's `server.tool(name, description, schema,
// handler)` shape so `registerTool` records the wrapped handler that
// would otherwise be handed to an MCP client. Kept structurally
// identical to the FakeServer in `policy.test.js`; not imported to
// preserve the parallel-duplication precedent set by the NGFW surface
// test.
class FakeServer {
  constructor() {
    this.registered = [];
  }
  tool(name, description, schema, handler) {
    this.registered.push({ name, description, schema, handler });
  }
  names() {
    return new Set(this.registered.map((r) => r.name));
  }
  byName(name) {
    return this.registered.find((r) => r.name === name);
  }
}

function buildSurface(profile) {
  // `_resetGateCachesForTests` clears the module-level
  // `registeredDescriptorNames` set so successive `buildSurface(...)`
  // calls under different profiles don't accumulate state. Without
  // this, `validateApexCoverage` would still pass — it checks set
  // membership, not equality — but the test would be implicitly
  // relying on a side effect of a previous run.
  _resetGateCachesForTests();
  // Real `.shifter.yaml` content (with the audit-path override
  // applied at module-level `before`) goes through the real
  // `loadPolicy`, so the surface suite covers the same startup path
  // `main()` uses.
  const policy = loadPolicy({ path: TMP_POLICY_PATH, profile });
  const server = new FakeServer();
  // Codex review #1202 cycle 3 finding 2 (class): capture descriptor
  // metadata through the `onRegisterDescriptor` hook on `policy.js`'s
  // `registerTool`. Production server context never sets this
  // callback (no live behavior change); tests use it to assert
  // `klass`, `untrusted_source`, `sensitive_args`, `is_write` on the
  // LIVE descriptors — the metadata the wrapper actually composes
  // gates from. Without this, "tool name X is registered under
  // profile Y" passes even when the descriptor's class was silently
  // changed to a different class in the same profile (which would
  // skip the secret_handle wrap, the producer fence, etc.).
  const descriptors = [];
  registerAllOpsTools({
    server,
    policy,
    onRegisterDescriptor: (d) => descriptors.push(d),
  });
  return { server, policy, descriptors };
}

// --- Hardcoded expected surface per profile ----------------------------
//
// Adding or removing a `registerTool(ctx, {...})` call in `index.js`
// MUST be accompanied by an edit here. That is the entire point of
// this file.

const EXPECTED_OBSERVABILITY_TOOLS = [
  "approve",
  "describe_log_streams",
  "get_log_events",
  "filter_log_events",
  "tail_logs",
  "list_ec2_instances",
  "list_ecs_tasks",
  "describe_ecs_service",
  "list_secrets",
  "describe_asg",
  "describe_target_health",
  "risk_dashboard",
  "risk_matrix",
  "list_s3_buckets",
  "list_s3_objects",
  "get_s3_object",
  "terraform_state",
  "cost_summary",
  "daily_spend",
];

const EXPECTED_NAMED_DB_READ_TOOLS = [
  "list_risks",
  "get_risk",
  "risk_audit_log",
  "list_ranges",
  "get_range",
  "list_subnet_allocations",
];

const EXPECTED_NAMED_DB_WRITE_TOOLS = [
  "create_risk",
  "update_risk",
  "delete_risk",
  "restore_risk",
  "add_risk_comment",
  "delete_risk_comment",
];

const EXPECTED_SECRET_HANDLE_TOOLS = ["get_secret"];
const EXPECTED_SSM_NAMED_TOOLS = ["run_manage_command"];

// Two-phase classes: every descriptor of these classes is registered
// as a `plan_<name>` / `execute_<name>` PAIR; the direct `<name>` does
// NOT appear in the surface.
const TWO_PHASE_SSM_ARBITRARY_BASES = [
  "ssm_send_command",
  "ssm_get_command_output",
];
const TWO_PHASE_DB_ARBITRARY_BASES = [
  "list_tables",
  "describe_table",
  "query",
  "execute",
];
const TWO_PHASE_INFRA_MUTATION_BASES = [
  "start_ec2_instance",
  "stop_ec2_instance",
  "terminate_ec2_instance",
  "restart_ecs_service",
  "reconcile_ranges",
];

const EXPECTED_DEV_BYPASS_TUNNEL_TOOLS = [
  "start_portal_test_tunnel",
  "stop_portal_test_tunnel",
];

// Codex review #1202 cycle 3 finding 2 (class): the descriptor metadata
// the wrapper actually composes gates from. Adding / changing /
// removing a producer's `untrusted_source`, a consumer's
// `untrusted_inputs`, `approve`'s `sensitive_args`, or `execute`'s
// `is_write` must update this file; the assertions below pull the
// matching descriptor out of the captured-descriptor list and check
// equality, so a regression that silently drops `untrusted_source`
// on `tail_logs` (which would skip producer fencing on log bodies)
// fails the suite.
const EXPECTED_PRODUCER_LABELS = {
  get_log_events: "logs",
  filter_log_events: "logs",
  tail_logs: "logs",
  ssm_get_command_output: "ssm_stdout",
  list_s3_objects: "s3",
  get_s3_object: "s3",
  terraform_state: "s3",
};

const EXPECTED_CONSUMER_INPUTS = {
  ssm_send_command: ["command"],
  query: ["sql"],
  execute: ["sql"],
  run_manage_command: ["command"],
};

function twoPhasePairs(bases) {
  return bases.flatMap((b) => [`plan_${b}`, `execute_${b}`]);
}

const EXPECTED_READ_ONLY = new Set([
  ...EXPECTED_OBSERVABILITY_TOOLS,
  ...EXPECTED_NAMED_DB_READ_TOOLS,
]);

const EXPECTED_STANDARD = new Set([
  ...EXPECTED_READ_ONLY,
  ...EXPECTED_NAMED_DB_WRITE_TOOLS,
  ...EXPECTED_SECRET_HANDLE_TOOLS,
  ...EXPECTED_SSM_NAMED_TOOLS,
]);

const EXPECTED_DESTRUCTIVE = new Set([
  ...EXPECTED_STANDARD,
  ...twoPhasePairs(TWO_PHASE_SSM_ARBITRARY_BASES),
  ...twoPhasePairs(TWO_PHASE_DB_ARBITRARY_BASES),
  ...twoPhasePairs(TWO_PHASE_INFRA_MUTATION_BASES),
  ...EXPECTED_DEV_BYPASS_TUNNEL_TOOLS,
]);

const ALL_TWO_PHASE_BASES = [
  ...TWO_PHASE_SSM_ARBITRARY_BASES,
  ...TWO_PHASE_DB_ARBITRARY_BASES,
  ...TWO_PHASE_INFRA_MUTATION_BASES,
];

// =====================================================================
// Scope bullet 1: Profile gating actually removes tools from the
// registered set (`read_only`, `standard`, `destructive`).
// =====================================================================

describe("mcp/ops profile gating removes tools from the registered set", () => {
  it("read_only profile exposes only observability + named_db_read tools", () => {
    const { server } = buildSurface("read_only");
    assert.deepStrictEqual(
      server.names(),
      EXPECTED_READ_ONLY,
      "read_only registration mismatch — update EXPECTED_READ_ONLY in this file AND the corresponding `registerTool` block in mcp/ops/index.js.",
    );
  });

  it("standard profile additionally exposes named_db_write, secret_handle, ssm_named", () => {
    const { server } = buildSurface("standard");
    assert.deepStrictEqual(
      server.names(),
      EXPECTED_STANDARD,
      "standard registration mismatch — update EXPECTED_STANDARD in this file.",
    );
  });

  it("destructive profile exposes every class, two-phase ones as plan_/execute_ pairs", () => {
    const { server } = buildSurface("destructive");
    assert.deepStrictEqual(
      server.names(),
      EXPECTED_DESTRUCTIVE,
      "destructive registration mismatch — update EXPECTED_DESTRUCTIVE in this file.",
    );
  });

  it("class-gated tools are ABSENT (not registered) when the profile excludes their class", () => {
    // The strong invariant: a disabled class produces NO `server.tool`
    // call. A "registered-but-refused-at-call-time" implementation
    // would let the tool name leak through `list_tools` and into the
    // LLM's tool catalog. Read_only must not expose any destructive
    // surface at all — assert the absence of every higher-class tool
    // name, including both direct names and the two-phase pairs.
    const { server } = buildSurface("read_only");
    const names = server.names();
    const forbidden = [
      ...EXPECTED_NAMED_DB_WRITE_TOOLS,
      ...EXPECTED_SECRET_HANDLE_TOOLS,
      ...EXPECTED_SSM_NAMED_TOOLS,
      ...EXPECTED_DEV_BYPASS_TUNNEL_TOOLS,
      ...ALL_TWO_PHASE_BASES,
      ...twoPhasePairs(ALL_TWO_PHASE_BASES),
    ];
    for (const name of forbidden) {
      assert.ok(
        !names.has(name),
        `read_only must NOT register \`${name}\`; profile gating removes it from the registered set.`,
      );
    }
  });
});

// =====================================================================
// Scope bullet 2: infra_mutation / ssm_arbitrary / db_arbitrary tools
// cannot bypass dry-run via missing flag.
//
// Class default `two_phase: true` (enforced as an ADR-014-R5 invariant
// by `_assertAdr014Invariants` in policy.js) means the original direct
// tool name is NEVER registered — only the `plan_<name>` /
// `execute_<name>` pair. Calling `execute_<name>` without a `plan_id`
// throws PolicyError (the `plan_id` argument is required is the
// structural gate).
// =====================================================================

describe("two-phase classes cannot execute via a missing-flag path", () => {
  it("direct tool names for infra_mutation / ssm_arbitrary / db_arbitrary are NEVER registered under destructive", () => {
    const { server } = buildSurface("destructive");
    const names = server.names();
    for (const base of ALL_TWO_PHASE_BASES) {
      assert.ok(
        !names.has(base),
        `Two-phase tool \`${base}\` must NOT register a direct entry under destructive; only \`plan_${base}\` + \`execute_${base}\` are permitted.`,
      );
      assert.ok(
        names.has(`plan_${base}`),
        `\`plan_${base}\` must be registered under destructive.`,
      );
      assert.ok(
        names.has(`execute_${base}`),
        `\`execute_${base}\` must be registered under destructive.`,
      );
    }
  });

  it("execute_<name> rejects calls that omit plan_id", async () => {
    const { server } = buildSurface("destructive");
    // Pick one representative tool per two-phase class so a future
    // class change is visible here too.
    const samples = ["execute_terminate_ec2_instance", "execute_query", "execute_ssm_send_command"];
    for (const name of samples) {
      const entry = server.byName(name);
      assert.ok(entry, `${name} must be in the registered surface`);
      await assert.rejects(
        () => entry.handler({}),
        (err) =>
          err instanceof PolicyError &&
          /plan_id argument is required/.test(err.message),
        `${name} must throw PolicyError when plan_id is missing.`,
      );
    }
  });

  it("plan_<name> issues a plan_id without invoking the underlying handler", async () => {
    const { server } = buildSurface("destructive");
    // `plan_terminate_ec2_instance` exercises the infra_mutation path.
    // The handler closure inside `index.js` would call AWS if it ran;
    // the plan-time wrapper short-circuits that and returns a stored
    // plan envelope, so this test reaching success proves the inner
    // handler was NOT invoked.
    const entry = server.byName("plan_terminate_ec2_instance");
    const result = await entry.handler({
      env: "prod",
      confirm_env: "prod",
      instance_id: "i-0123456789abcdef0",
    });
    assert.ok(result?.content?.[0]?.type === "text");
    const payload = JSON.parse(result.content[0].text);
    assert.ok(
      /^[0-9a-f-]{36}$/.test(payload.plan_id),
      `plan_id must be a UUID; got ${payload.plan_id}`,
    );
    assert.equal(payload.ttl_seconds, 60);
    assert.equal(payload.summary.tool, "terminate_ec2_instance");
    assert.equal(payload.summary.class, "infra_mutation");
    assert.equal(payload.summary.env, "prod");
  });
});

// =====================================================================
// Scope bullet 3: `secret_handle` tools cannot return raw secret values
// in any response path.
//
// The surface invariant is structural: `class_defaults.secret_handle`
// declares `return_mode: handle` in the live `.shifter.yaml`, which is
// enforced as an ADR-014-R5 invariant by `_assertAdr014Invariants` in
// `policy.js`. Tampering with this field (or removing it) fails
// `loadPolicy` at startup. The wrap mechanism itself (raw secret →
// `shf-secret:<uuid>`) is unit-tested in `policy.test.js`; here we
// lock in that the LIVE policy keeps the class invariant and that the
// LIVE registered surface includes `get_secret` under its expected
// classes only.
// =====================================================================

describe("secret_handle tools cannot return raw secret values", () => {
  it("the live policy declares class_defaults.secret_handle.return_mode = 'handle'", () => {
    const { policy } = buildSurface("standard");
    const defaults = policy.classDefaults("secret_handle");
    assert.equal(
      defaults.return_mode,
      "handle",
      "ADR-014-R5 requires class_defaults.secret_handle.return_mode = 'handle'; loadPolicy must reject any tampered value.",
    );
  });

  it("get_secret's LIVE descriptor is class secret_handle (and list_secrets is observability)", () => {
    // Codex review #1202 cycle 3 finding 2 (class): assert the
    // descriptor metadata, not just the registered tool name. If a
    // future edit silently re-classed `get_secret` from
    // `secret_handle` to another standard-only class (e.g.
    // `observability` to "make list_tools cleaner"), the secret-wrap
    // would stop firing AND a name-only assertion would still pass.
    // Re-asserting `klass` against the live descriptor closes that.
    const { server, descriptors } = buildSurface("standard");
    const getSecret = descriptors.find((d) => d.name === "get_secret");
    assert.ok(getSecret, "get_secret descriptor must reach registerTool");
    assert.equal(
      getSecret.klass,
      "secret_handle",
      "get_secret.klass must be 'secret_handle' so _wrapSecretReturn fires on success paths.",
    );
    const listSecrets = descriptors.find((d) => d.name === "list_secrets");
    assert.ok(listSecrets, "list_secrets descriptor must reach registerTool");
    assert.equal(
      listSecrets.klass,
      "observability",
      "list_secrets.klass must stay 'observability' — it returns discovery metadata only, no secret material.",
    );
    // And both must reach the registered surface under standard.
    const names = server.names();
    assert.ok(names.has("get_secret"));
    assert.ok(names.has("list_secrets"));
  });

  it("get_secret is ABSENT under read_only (secret_handle class disabled)", () => {
    const { server } = buildSurface("read_only");
    assert.ok(
      !server.names().has("get_secret"),
      "get_secret must NOT be registered when the active profile excludes secret_handle.",
    );
  });
});

// =====================================================================
// Scope bullet 4: Prod-touching tools refuse without `confirm_env="prod"`.
// =====================================================================

describe("prod calls require confirm_env='prod'", () => {
  it("plan_terminate_ec2_instance({env:'prod'}) without confirm_env throws PolicyError", async () => {
    const { server } = buildSurface("destructive");
    const entry = server.byName("plan_terminate_ec2_instance");
    await assert.rejects(
      () => entry.handler({ env: "prod", instance_id: "i-0123456789abcdef0" }),
      (err) =>
        err instanceof PolicyError &&
        /env="prod" requires confirm_env="prod"/.test(err.message),
    );
  });

  it("plan_query({env:'prod'}) without confirm_env throws PolicyError (class-wide gate)", async () => {
    // Re-running the gate on a different class proves env policy is
    // class-wide, not tool-specific.
    const { server } = buildSurface("destructive");
    const entry = server.byName("plan_query");
    await assert.rejects(
      () => entry.handler({ env: "prod", sql: "select 1" }),
      (err) =>
        err instanceof PolicyError &&
        /env="prod" requires confirm_env="prod"/.test(err.message),
    );
  });

  it("plan_terminate_ec2_instance({env:'prod', confirm_env:'prod'}) is accepted", async () => {
    const { server } = buildSurface("destructive");
    const entry = server.byName("plan_terminate_ec2_instance");
    const result = await entry.handler({
      env: "prod",
      confirm_env: "prod",
      instance_id: "i-0123456789abcdef0",
    });
    const payload = JSON.parse(result.content[0].text);
    assert.equal(payload.summary.env, "prod");
  });
});

// =====================================================================
// Scope bullet 5: `dev_bypass_tunnel` tool descriptions don't contain
// bypass-procedure language or `/dev-login/` URLs.
// =====================================================================

describe("dev_bypass_tunnel descriptions are redacted", () => {
  it("start_portal_test_tunnel description is the redacted constant verbatim", () => {
    const { server } = buildSurface("destructive");
    const entry = server.byName("start_portal_test_tunnel");
    assert.ok(entry, "start_portal_test_tunnel must be registered under destructive");
    assert.equal(
      entry.description,
      REDACTED_DESCRIPTION,
      "Description must be the policy.js REDACTED_DESCRIPTION constant verbatim — not phrase-stripped — to guarantee no bypass procedure language can leak via list_tools.",
    );
  });

  it("stop_portal_test_tunnel description is the redacted constant verbatim", () => {
    const { server } = buildSurface("destructive");
    const entry = server.byName("stop_portal_test_tunnel");
    assert.equal(entry.description, REDACTED_DESCRIPTION);
  });

  it("redacted descriptions contain no bypass-procedure language or /dev-login/ URLs", () => {
    // Defense-in-depth scan that catches a future regression where
    // REDACTED_DESCRIPTION is loosened. The hardcoded substrings are
    // the ones operators most commonly grep `list_tools` for when
    // looking up the bypass procedure — they are exactly what ADR-014-R6
    // wants to keep out of the LLM's tool catalog.
    const { server } = buildSurface("destructive");
    for (const name of EXPECTED_DEV_BYPASS_TUNNEL_TOOLS) {
      const entry = server.byName(name);
      for (const forbidden of ["/dev-login/", "bypass", "Cognito", "MFA"]) {
        assert.ok(
          !entry.description.includes(forbidden),
          `${name} description must not include \`${forbidden}\`; got: ${entry.description}`,
        );
      }
    }
  });
});

// =====================================================================
// Scope bullet 6: Untrusted-input fencing + acknowledge flag enforced
// on consumer tools.
//
// Consumer tools (those that accept free-form text that becomes an
// operative payload — SQL, shell commands) declare `untrusted_inputs`
// in their descriptor; the wrapper refuses calls whose declared field
// values contain a producer fence opener unless
// `acknowledge_untrusted_input: true` is set.
//
// Producer tools (those that return text from outside the operator's
// trust boundary) declare `untrusted_source` in their descriptor; the
// wrapper validates the label against `.shifter.yaml`'s
// `untrusted_sources` allowlist at registration time. If any producer
// in `mcp/ops/index.js` had a malformed or unallowlisted label,
// `registerAllOpsTools` would throw — so the fact that
// `buildSurface("destructive")` returns without throwing is itself the
// proof for the producer side.
// =====================================================================

describe("untrusted-input fencing + acknowledge flag", () => {
  it("plan_query rejects fenced SQL without acknowledge_untrusted_input", async () => {
    const { server } = buildSurface("destructive");
    const entry = server.byName("plan_query");
    await assert.rejects(
      () =>
        entry.handler({
          env: "dev",
          sql: "[UNTRUSTED:logs:BEGIN]select 1[UNTRUSTED:logs:END]",
        }),
      (err) =>
        err instanceof PolicyError &&
        /contains an untrusted-input fence/.test(err.message),
    );
  });

  it("plan_query accepts fenced SQL when acknowledge_untrusted_input is true", async () => {
    const { server } = buildSurface("destructive");
    const entry = server.byName("plan_query");
    const result = await entry.handler({
      env: "dev",
      sql: "[UNTRUSTED:logs:BEGIN]select 1[UNTRUSTED:logs:END]",
      acknowledge_untrusted_input: true,
    });
    const payload = JSON.parse(result.content[0].text);
    assert.equal(payload.summary.tool, "query");
  });

  it("plan_execute rejects fenced SQL without acknowledge_untrusted_input", async () => {
    const { server } = buildSurface("destructive");
    const entry = server.byName("plan_execute");
    await assert.rejects(
      () =>
        entry.handler({
          env: "dev",
          sql: "[UNTRUSTED:logs:BEGIN]update foo set a=1[UNTRUSTED:logs:END]",
        }),
      (err) =>
        err instanceof PolicyError &&
        /contains an untrusted-input fence/.test(err.message),
    );
  });

  it("plan_ssm_send_command rejects fenced command without acknowledge_untrusted_input", async () => {
    const { server } = buildSurface("destructive");
    const entry = server.byName("plan_ssm_send_command");
    await assert.rejects(
      () =>
        entry.handler({
          env: "dev",
          instance_id: "i-0123456789abcdef0",
          command: "[UNTRUSTED:logs:BEGIN]uname -a[UNTRUSTED:logs:END]",
        }),
      (err) =>
        err instanceof PolicyError &&
        /contains an untrusted-input fence/.test(err.message),
    );
  });

  it("consumer descriptors expose acknowledge_untrusted_input on the registered schema", () => {
    // The wrapper's `_augmentSchemaWithControlKeys` adds an
    // `acknowledge_untrusted_input` Zod field to consumer descriptors'
    // schemas so MCP clients see it in `list_tools`. Its absence on
    // the registered schema would mean the agent has no idiomatic way
    // to opt in to fenced input — and would be a silent regression of
    // the Phase 4 contract.
    const { server } = buildSurface("destructive");
    for (const name of ["plan_query", "plan_execute", "plan_ssm_send_command"]) {
      const entry = server.byName(name);
      assert.ok(
        entry.schema?.acknowledge_untrusted_input,
        `${name} registered schema must include acknowledge_untrusted_input.`,
      );
    }
  });

  it("registering all descriptors succeeds — every producer's untrusted_source label is in the allowlist", () => {
    // If any descriptor declared a malformed or unallowlisted
    // `untrusted_source` (e.g. typo `s33` instead of `s3`),
    // `registerTool` would throw `PolicyError` at registration time.
    // We re-run `buildSurface` here under each profile to make the
    // load-bearing assertion explicit; the previous tests rely on
    // this implicitly.
    assert.doesNotThrow(() => buildSurface("read_only"));
    assert.doesNotThrow(() => buildSurface("standard"));
    assert.doesNotThrow(() => buildSurface("destructive"));
  });

  it("LIVE producer descriptors declare the expected untrusted_source labels", () => {
    // Codex review #1202 cycle 3 finding 2 (class): asserting only
    // "registering succeeds" proves that any declared producer
    // labels are allowlist-valid — but a regression that DROPS the
    // `untrusted_source` field on `tail_logs` (so the wrapper stops
    // fencing log bodies) would still pass that assertion. Locking
    // in expected labels per producer closes that.
    const { descriptors, policy } = buildSurface("destructive");
    const allow = policy.untrustedSources();
    for (const [name, expectedLabel] of Object.entries(EXPECTED_PRODUCER_LABELS)) {
      const d = descriptors.find((x) => x.name === name);
      assert.ok(d, `producer descriptor '${name}' must reach registerTool`);
      assert.equal(
        d.untrusted_source,
        expectedLabel,
        `${name}.untrusted_source must equal '${expectedLabel}' (drives _wrapUntrustedSource fencing).`,
      );
      assert.ok(
        allow.has(d.untrusted_source),
        `${name}.untrusted_source '${d.untrusted_source}' must be in .shifter.yaml's untrusted_sources allowlist.`,
      );
    }
  });

  it("LIVE consumer descriptors declare the expected untrusted_inputs fields", () => {
    // Same shape as the producer assertion above. Silently dropping
    // `untrusted_inputs: ["sql"]` from `query` would let fenced SQL
    // bypass the acknowledgement gate, and a name-only assertion
    // would not notice.
    const { descriptors } = buildSurface("destructive");
    for (const [name, expectedInputs] of Object.entries(EXPECTED_CONSUMER_INPUTS)) {
      const d = descriptors.find((x) => x.name === name);
      assert.ok(d, `consumer descriptor '${name}' must reach registerTool`);
      assert.deepStrictEqual(
        d.untrusted_inputs,
        expectedInputs,
        `${name}.untrusted_inputs must equal ${JSON.stringify(expectedInputs)} (drives _enforceUntrustedInputGate).`,
      );
    }
  });

  it("LIVE execute descriptor declares is_write: true (so class-keyed apex requires_write fires on it)", () => {
    // The class-keyed apex rule `{class: db_arbitrary, env: prod,
    // operation_kind: execute, requires_write: true}` in
    // .shifter.yaml only matches descriptors whose `is_write` is
    // `true`. Without this on `execute`, prod `execute` would slip
    // past apex out-of-band confirmation while `query` /
    // `list_tables` correctly stay out — proving the field is
    // load-bearing for ADR-014-R6 apex coverage.
    const { descriptors } = buildSurface("destructive");
    const exec = descriptors.find((d) => d.name === "execute");
    assert.ok(exec, "execute descriptor must reach registerTool");
    assert.equal(exec.is_write, true, "execute.is_write must be true so apex requires_write rules match it.");
  });
});

// =====================================================================
// Scope bullet 7: Apex tools require terminal confirmation token.
//
// Surface assertions are structural: the apex_operations rules in
// `.shifter.yaml` must point at LIVE registered descriptors, and the
// `approve` tool (which consumes the token) must be available in every
// profile. The behavioral apex flow (stderr-only token emission, 60s
// timeout, `consumeApexToken` releases the parked handler) is
// exhaustively covered in `policy.test.js`; replicating it here would
// duplicate test logic without adding surface coverage.
// =====================================================================

describe("apex out-of-band confirmation surface", () => {
  it("registerAllOpsTools validates apex coverage — every apex_operations[*].tool maps to a real descriptor", () => {
    // `registerAllOpsTools` calls `validateApexCoverage(ctx.policy)`
    // as its last step. If any `apex_operations[*].tool` in
    // `.shifter.yaml` pointed at a typoed / non-registered descriptor,
    // `buildSurface` would throw PolicyError. Reaching this assertion
    // proves the live config is internally consistent.
    assert.doesNotThrow(() => buildSurface("destructive"));
  });

  it("every apex_operations[*].tool rule maps to a registered execute_<name>", () => {
    const { server, policy } = buildSurface("destructive");
    const names = server.names();
    for (const rule of policy.apexOperations()) {
      if (!rule.tool) continue;
      // The class default for the rule's class is `two_phase: true`,
      // so the apex-gated entry point is `execute_<name>`, never the
      // direct name. The rule's `operation_kind` is "execute" in the
      // shipped policy.
      assert.ok(
        names.has(`execute_${rule.tool}`),
        `apex_operations rule for tool '${rule.tool}' must point at a registered \`execute_${rule.tool}\``,
      );
    }
  });

  it("the `approve` tool is registered under every profile (without it no apex op can complete)", () => {
    for (const profile of ["read_only", "standard", "destructive"]) {
      const { server } = buildSurface(profile);
      assert.ok(
        server.names().has("approve"),
        `\`approve\` must be registered under ${profile}; otherwise no apex op can release its parked handler.`,
      );
    }
  });

  it("the LIVE approve descriptor declares sensitive_args: ['token']", () => {
    // Codex review #1202 cycle 3 finding 2 (class): the schema check
    // alone passed even when the `sensitive_args: ["token"]` line on
    // the approve descriptor was removed (the `token` schema field
    // is the registered Zod entry, not the sensitive-args list).
    // Assert the live descriptor metadata directly: that field is
    // what drives `_safeOutputArgs` to replace the token bytes with
    // `<redacted>` before they reach the audit log.
    const { descriptors } = buildSurface("destructive");
    const approve = descriptors.find((d) => d.name === "approve");
    assert.ok(approve, "approve descriptor must reach registerTool");
    assert.deepStrictEqual(
      approve.sensitive_args,
      ["token"],
      "approve.sensitive_args must equal ['token'] so apex tokens never land in the audit log.",
    );
    assert.equal(approve.klass, "observability");
  });

  it("driving approve through the wrapped handler redacts the token from the audit record", async () => {
    // Effect-based proof: even with the descriptor metadata above,
    // a future change that re-wired `_safeOutputArgs` could still
    // silently leak the token. This test invokes the wrapped
    // `approve` handler against an unknown token (so
    // `consumeApexToken` returns false and the handler errors
    // cleanly), then inspects the audit file the wrapper wrote.
    // The audit record must (a) reference the approve invocation,
    // (b) replace the token field with `<redacted>`, and (c)
    // contain ZERO occurrences of the literal token bytes anywhere
    // in the file's contents.
    const { server } = buildSurface("destructive");
    const entry = server.byName("approve");
    // 32 hex characters — passes the descriptor's Zod regex if the
    // SDK were enforcing schema, and matches the apex-token shape
    // the wrapper expects. Distinct from any real apex token.
    const SYNTHETIC_TOKEN = "0".repeat(31) + "1";
    const result = await entry.handler({ token: SYNTHETIC_TOKEN });
    assert.equal(
      result.isError,
      true,
      "approve with an unknown token must return an isError envelope.",
    );
    // `consumeApexToken` directly with the synthetic token must
    // also return false — proves the token never entered the
    // pending-apex map by way of the audit/handler path.
    assert.equal(consumeApexToken(SYNTHETIC_TOKEN), false);

    const auditContent = readFileSync(TMP_AUDIT_PATH, "utf-8");
    assert.ok(
      auditContent.includes('"tool":"approve"'),
      `audit must record the approve invocation; got:\n${auditContent}`,
    );
    assert.ok(
      !auditContent.includes(SYNTHETIC_TOKEN),
      `audit must NOT contain the literal token bytes; got:\n${auditContent}`,
    );
    assert.ok(
      /"token"\s*:\s*"<redacted>"/.test(auditContent),
      `audit must render approve.token as "<redacted>"; got:\n${auditContent}`,
    );
  });
});
