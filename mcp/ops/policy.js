// Per-tool policy layer for the shifter-ops MCP server.
//
// `mcp/ops` is an operator agent surface (ADR-014-R5): the intended
// client is the operator's own trusted agent loop, and agents are
// *meant* to perform writes, mutations, SSM execution, and secret
// retrieval as routine range-operations work. The policy layer gates
// each tool by capability class so the blast radius of any single
// call is bounded against prompt injection and agent error, without
// removing the underlying capability.
//
// See docs/architecture/mcp-ops-privileged-surface-preflight-777.md
// for the threat model and mcp/ops/SECURITY.md for the operational
// rules.

import { readFileSync } from "node:fs";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import yaml from "yaml";
import { z } from "zod";
import { appendAuditRecord, sanitizeArgs } from "./audit.js";

const SUPPORTED_VERSION = 1;

const REQUIRED_TOP_LEVEL_KEYS = [
  "version",
  "classes",
  "session_profile",
  "environments",
  "class_defaults",
  "audit",
];

export class PolicyError extends Error {
  constructor(message) {
    super(message);
    this.name = "PolicyError";
  }
}

// Nested-shape validators. Top-level validation is hand-written so
// PolicyError messages stay tight; these Zod schemas enforce the
// interior shapes that handler-wrap code consumes once Phases 2-4
// ship. A typo like `prod_requires_confirm: 'true'` or a malformed
// `rate_cap` must fail closed at startup rather than silently being
// interpreted as weaker policy.
const ClassNameSchema = z.string().min(1);
const RateCapSchema = z
  .object({
    count: z.number().int().positive(),
    window_seconds: z.number().int().positive(),
  })
  .strict();
const ClassDefaultsValueSchema = z
  .object({
    execute_default: z.boolean().optional(),
    two_phase: z.boolean().optional(),
    rate_cap: RateCapSchema.optional(),
    idempotency_key: z.enum(["required", "optional"]).optional(),
    return_mode: z.enum(["handle", "value"]).optional(),
    allowed_envs: z.array(z.enum(["dev", "prod"])).nonempty().optional(),
    description_redaction: z.boolean().optional(),
  })
  .strict();
const EnvironmentsSchema = z
  .object({
    default: z.enum(["dev", "prod"]),
    prod_requires_confirm: z.boolean(),
  })
  .strict();
const AuditSchema = z
  .object({
    enabled: z.boolean(),
    path: z.string().min(1),
    redact: z.array(z.string().min(1)),
  })
  .strict();
// Per-tool override entries hold only `overrides:` value tweaks; the
// tool's capability class is set authoritatively by the descriptor
// passed to registerTool. Allowing `tools.<name>.class` would create
// two competing sources of truth for the most important policy
// decision; instead, classes live in code (descriptors) and config
// only tunes class-level defaults per tool.
const ToolOverrideSchema = z
  .object({
    overrides: ClassDefaultsValueSchema.optional(),
  })
  .strict();
const ToolsMapSchema = z.record(z.string().min(1), ToolOverrideSchema);

// Phase 4 #1200: apex out-of-band approval rules. Each rule is keyed
// by either tool OR class (exactly one), AND env, AND operation_kind.
// `requires_write: true` further restricts class-keyed rules to
// descriptors marked `is_write: true` so a class like `db_arbitrary`
// can apex on `execute` but not on read-only `query` / `list_tables`.
const ApexOpEntrySchema = z
  .object({
    tool: z.string().min(1).optional(),
    class: z.string().min(1).optional(),
    env: z.enum(["dev", "prod"]),
    operation_kind: z.enum(["plan", "execute", "direct"]),
    requires_write: z.boolean().optional(),
  })
  .strict()
  .refine((v) => Boolean(v.tool) !== Boolean(v.class), {
    message: "exactly one of 'tool' or 'class' must be set",
  })
  // Codex review #1201 cycle 2 finding: `requires_write` only makes
  // sense as a refinement on a class-keyed rule (it filters which
  // descriptors of a class are apex-gated). On a tool-keyed rule the
  // tool is already named exactly, so requires_write would either
  // be redundant (when the tool is is_write) or silently disable the
  // gate (when it isn't). Reject the combination instead of letting
  // a valid-looking config fail open.
  .refine((v) => !(v.requires_write === true && v.tool), {
    message: "requires_write may only be set on class-keyed apex rules, not tool-keyed",
  });
const ApexOperationsSchema = z.array(ApexOpEntrySchema);

// Phase 4 #1200: untrusted-input source label allowlist. The source
// label that producer descriptors embed in `[UNTRUSTED:<source>:...]`
// fences MUST appear in this list, so a typo or attacker-controlled
// label can't widen the contract the LLM sees.
const UntrustedSourceLabelSchema = z
  .string()
  .regex(/^[a-z][a-z0-9_]{0,31}$/, "must match [a-z][a-z0-9_]{0,31}");
const UntrustedSourcesSchema = z.array(UntrustedSourceLabelSchema).nonempty();

function _zodValidate(label, schema, value) {
  const result = schema.safeParse(value);
  if (!result.success) {
    const issues = result.error.issues
      .slice(0, 3)
      .map((i) => {
        const path = i.path.length ? `.${i.path.join(".")}` : "";
        return `${label}${path}: ${i.message}`;
      })
      .join("; ");
    throw new PolicyError(`policy: ${issues}`);
  }
  return result.data;
}

// Semantic invariants required by ADR-014-R5/R6 on every operator
// agent surface using this policy module. Shape validation
// (Zod above) catches typos and unsafe values; these invariants
// catch *structurally valid configs that would silently weaken the
// boundary*. Example: an `infra_mutation` class with
// `execute_default: true` parses cleanly but violates R5's
// "dry-run defaults for destructive and arbitrary classes." Bumping
// these requires bumping ADR-014 too.
const ADR_014_CLASS_INVARIANTS = {
  infra_mutation: { execute_default: false, two_phase: true },
  ssm_arbitrary: { execute_default: false, two_phase: true },
  db_arbitrary: { execute_default: false, two_phase: true },
  named_db_write: { idempotency_key: "required" },
  secret_handle: { return_mode: "handle" },
  dev_bypass_tunnel: {
    allowed_envs: ["dev"],
    description_redaction: true,
  },
};

function _deepEqualArray(a, b) {
  return (
    Array.isArray(a) &&
    Array.isArray(b) &&
    a.length === b.length &&
    a.every((v, i) => v === b[i])
  );
}

function _assertAdr014Invariants(raw) {
  if (raw.environments.prod_requires_confirm !== true) {
    throw new PolicyError(
      "policy: environments.prod_requires_confirm must be true (ADR-014-R5)",
    );
  }
  if (raw.audit.enabled !== true) {
    throw new PolicyError("policy: audit.enabled must be true (ADR-014-R5)");
  }
  for (const [klass, required] of Object.entries(ADR_014_CLASS_INVARIANTS)) {
    if (!raw.classes.includes(klass)) continue;
    const defaults = raw.class_defaults[klass];
    for (const [key, expected] of Object.entries(required)) {
      const actual = defaults[key];
      const ok = Array.isArray(expected)
        ? _deepEqualArray(actual, expected)
        : actual === expected;
      if (!ok) {
        throw new PolicyError(
          `policy: class_defaults.${klass}.${key} must be ${JSON.stringify(expected)} (ADR-014-R5)`,
        );
      }
    }
  }
}

// Pure parser — takes the parsed `mcp_ops:` namespace as a plain JS
// object and returns a Policy. Side-effect-free so tests can build
// fixtures without touching the filesystem.
function _assertTopLevelShape(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new PolicyError("policy: top-level value must be an object");
  }
  for (const key of REQUIRED_TOP_LEVEL_KEYS) {
    if (!(key in raw)) {
      throw new PolicyError(`policy: missing required key '${key}'`);
    }
  }
  if (raw.version !== SUPPORTED_VERSION) {
    throw new PolicyError(
      `policy: unsupported version ${raw.version}; expected ${SUPPORTED_VERSION}`,
    );
  }
  if (!Array.isArray(raw.classes) || raw.classes.length === 0) {
    throw new PolicyError("policy: 'classes' must be a non-empty array");
  }
}

// class_defaults MUST have an entry for every declared class, and
// MUST NOT have entries for undeclared classes. Each entry MUST be
// an object (even if empty). The wrapper depends on every declared
// class having a defaults block; a silent {} fallback would let a
// future class slip in without gates wired up.
function _assertClassDefaults(raw, declaredClasses) {
  const cd = raw.class_defaults;
  if (!cd || typeof cd !== "object" || Array.isArray(cd)) {
    throw new PolicyError("policy: 'class_defaults' must be an object");
  }
  for (const klass of raw.classes) {
    if (!(klass in cd)) {
      throw new PolicyError(
        `policy: 'class_defaults' is missing an entry for declared class '${klass}'`,
      );
    }
    _zodValidate(`class_defaults.${klass}`, ClassDefaultsValueSchema, cd[klass]);
  }
  for (const key of Object.keys(cd)) {
    if (!declaredClasses.has(key)) {
      throw new PolicyError(
        `policy: 'class_defaults' has entry for '${key}', which is not in 'classes'`,
      );
    }
  }
}

// Tools: per-tool override map (may be empty / absent). Each entry
// is strict-shaped so a typo doesn't bypass the policy.
function _assertToolsOverrides(raw, declaredClasses) {
  if (!("tools" in raw) || raw.tools === null) return;
  if (typeof raw.tools !== "object" || Array.isArray(raw.tools)) {
    throw new PolicyError("policy: 'tools' must be an object (or omitted)");
  }
  _zodValidate("tools", ToolsMapSchema, raw.tools);
  // ToolOverrideSchema enforces shape; this loop catches a class
  // reference that points outside the declared `classes:` array.
  for (const [toolName, override] of Object.entries(raw.tools)) {
    if (override.class !== undefined && !declaredClasses.has(override.class)) {
      throw new PolicyError(
        `policy: 'tools.${toolName}.class' is '${override.class}', which is not in 'classes'`,
      );
    }
  }
}

function _assertSessionProfiles(raw, declaredClasses) {
  const sp = raw.session_profile;
  if (
    !sp ||
    typeof sp !== "object" ||
    !sp.profiles ||
    typeof sp.profiles !== "object"
  ) {
    throw new PolicyError("policy: 'session_profile.profiles' must be an object");
  }
  for (const [profileName, classList] of Object.entries(sp.profiles)) {
    if (!Array.isArray(classList)) {
      throw new PolicyError(
        `policy: profile '${profileName}' must be an array of class names`,
      );
    }
    for (const klass of classList) {
      if (!declaredClasses.has(klass)) {
        throw new PolicyError(
          `policy: profile '${profileName}' references unknown class '${klass}'`,
        );
      }
    }
  }
}

function _resolveActiveProfile(raw, opts) {
  const sp = raw.session_profile;
  const activeProfileName = opts.profile ?? sp.default;
  if (!activeProfileName || !sp.profiles[activeProfileName]) {
    throw new PolicyError(`policy: unknown active profile '${activeProfileName}'`);
  }
  return activeProfileName;
}

function _assertApexOperations(raw, declaredClasses) {
  if (raw.apex_operations === undefined) return;
  _zodValidate("apex_operations", ApexOperationsSchema, raw.apex_operations);
  for (const op of raw.apex_operations) {
    if (op.class && !declaredClasses.has(op.class)) {
      throw new PolicyError(
        `policy: apex_operations entry references unknown class '${op.class}'`,
      );
    }
  }
}

function _assertUntrustedSources(raw) {
  if (raw.untrusted_sources === undefined) return;
  _zodValidate("untrusted_sources", UntrustedSourcesSchema, raw.untrusted_sources);
}

export function parsePolicy(raw, opts = {}) {
  _assertTopLevelShape(raw);
  const declaredClasses = new Set(raw.classes);
  _assertClassDefaults(raw, declaredClasses);
  // Environments: strict shape (default in {dev,prod}, prod_requires_confirm
  // strictly boolean). A typo like `prod_requires_confirm: 'true'` must fail.
  _zodValidate("environments", EnvironmentsSchema, raw.environments);
  // Audit: strict shape (enabled boolean, path non-empty string, redact
  // string-array).
  _zodValidate("audit", AuditSchema, raw.audit);
  _assertToolsOverrides(raw, declaredClasses);
  _assertSessionProfiles(raw, declaredClasses);
  _assertApexOperations(raw, declaredClasses);
  _assertUntrustedSources(raw);
  const activeProfileName = _resolveActiveProfile(raw, opts);
  // Final layer: enforce ADR-014-R5/R6 semantic invariants. Shape
  // checks above don't catch a config that's structurally valid but
  // weakens the boundary.
  _assertAdr014Invariants(raw);
  return new Policy(raw, activeProfileName);
}

// Load `.shifter.yaml` from disk and parse the `mcp_ops:` namespace.
// `profile` overrides `mcp_ops.session_profile.default` (typically
// from the `SHIFTER_OPS_PROFILE` env var at server startup).
export function loadPolicy({ path, profile } = {}) {
  if (!path) {
    throw new PolicyError("loadPolicy: 'path' is required");
  }
  const text = readFileSync(path, "utf-8");
  const doc = yaml.parse(text);
  if (!doc || typeof doc !== "object" || !("mcp_ops" in doc)) {
    throw new PolicyError(
      `loadPolicy: ${path} is missing required 'mcp_ops:' namespace`,
    );
  }
  return parsePolicy(doc.mcp_ops, { profile });
}

// Read the SHIFTER_OPS_PROFILE env var with sensible fallback. The
// server's main entrypoint uses this so the policy module stays
// pure.
export function profileFromEnv(env = process.env) {
  const raw = env.SHIFTER_OPS_PROFILE;
  if (!raw) return undefined;
  const trimmed = raw.trim();
  if (!trimmed) return undefined;
  return trimmed;
}

export class Policy {
  constructor(raw, activeProfile) {
    this._raw = raw;
    this.profile = activeProfile;
    this._declaredClasses = new Set(raw.classes);
    this._activeClasses = new Set(raw.session_profile.profiles[activeProfile]);
  }

  classDeclared(klass) {
    return this._declaredClasses.has(klass);
  }

  classEnabled(klass) {
    return this._activeClasses.has(klass);
  }

  classDefaults(klass) {
    if (!this._declaredClasses.has(klass)) {
      throw new PolicyError(`classDefaults: unknown class '${klass}'`);
    }
    // parsePolicy already guarantees every declared class has a
    // class_defaults entry; no `?? {}` fallback here on purpose.
    return this._raw.class_defaults[klass];
  }

  toolOverride(toolName) {
    return this._raw.tools?.[toolName] ?? null;
  }

  envDefault() {
    return this._raw.environments.default;
  }

  envProdRequiresConfirm() {
    return this._raw.environments.prod_requires_confirm === true;
  }

  auditConfig() {
    return this._raw.audit;
  }

  apexOperations() {
    return this._raw.apex_operations ?? [];
  }

  untrustedSources() {
    if (!this._untrustedSourcesCache) {
      this._untrustedSourcesCache = new Set(this._raw.untrusted_sources ?? []);
    }
    return this._untrustedSourcesCache;
  }

  // Convenience for tests / debuggers — returns the resolved
  // class-defaults merged with any per-tool override.
  resolveToolPolicy(toolName, klass) {
    if (!this._declaredClasses.has(klass)) {
      throw new PolicyError(`resolveToolPolicy: unknown class '${klass}'`);
    }
    const base = this._raw.class_defaults[klass]; // guaranteed by parsePolicy
    const override = this._raw.tools?.[toolName]?.overrides ?? {};
    return { ...base, ...override };
  }
}

// ===========================================================================
// Phase 2 gates (#1198)
//
// `registerTool` now composes five gates around every tool handler.
// Each gate is class-driven from `.shifter.yaml`'s `class_defaults`
// block so the policy file remains the source of truth; the wrapper
// reads the per-class flags and chooses whether the gate fires.
//
// 1. **Env policy**  — `confirm_env="prod"` required for prod calls.
// 2. **Dry-run defaults** — classes with `execute_default: false`
//    return a preview unless `args.execute === true`.
// 3. **Description redaction** — classes with `description_redaction:
//    true` get their description replaced before it reaches
//    `server.tool()` (so `list_tools` cannot surface bypass
//    procedures, per ADR-014-R6).
// 4. **Idempotency keys** — classes with `idempotency_key: "required"`
//    refuse calls without `args.idempotency_key`; same key on retry
//    returns the cached result for a TTL.
// 5. **Secret handles** — classes with `return_mode: "handle"` wrap
//    the handler's return into `{ content: [{ text: "shf-secret:<uuid>" }] }`;
//    the raw value lives only inside this process.
// ===========================================================================

const IDEMPOTENCY_TTL_MS = 15 * 60 * 1000; // 15 minutes
const SECRET_HANDLE_TTL_MS = 15 * 60 * 1000; // 15 minutes

// Phase 3 (#1199): two-phase plan store. Each plan_<name> call stores
// the verbatim caller args here, returns the plan_id, and the matching
// execute_<name>(plan_id) consumes the entry atomically before running
// the handler. The store is intentionally in-process, volatile, and
// bounded — long agent conversations cannot pre-plan-and-batch
// destructive ops.
const PLAN_TTL_MS = 60 * 1000;
const MAX_PLAN_STORE_SIZE = 64;
const planStore = new Map(); // plan_id -> { tool, klass, args, fingerprint, expiresAt }

// Phase 3 (#1199): per-class sliding-window rate-cap state. The window
// is keyed by class (not tool, env, or profile) because the issue spec
// asks for per-class caps; per-tool tunings come from
// `tools.<name>.overrides.rate_cap` but share the class window so a
// tool that loosens the count doesn't get a separate quota bucket. A
// dry-run / plan_<name> call does NOT consume capacity; only
// execute_<name> (and direct execution for non-two-phase classes)
// does.
const rateCapWindows = new Map(); // klass -> sorted timestamp[]

// Phase 4 (#1200): pending apex approval state. Each apex-gated
// execute_<name> generates a single-use token, prints it to stderr,
// and parks on a promise registered here. The dedicated `approve`
// MCP tool consumes the token and releases the parked handler. On
// timeout (60s) the entry is removed and the parked handler rejects.
const APEX_APPROVAL_TTL_MS = 60 * 1000;
const APEX_TOKEN_BYTES = 16; // 128-bit, hex-encoded to 32 chars
// Codex review #1201 cycle 3 finding 4: bound the parked-promise
// queue so an agent loop can't enqueue an unbounded number of pending
// apex requests (each carrying a 60s timer) before any operator
// confirms. The plan store is bounded for the same reason. 16 keeps
// the queue small enough that the operator can keep up with prompts
// while still allowing legitimate concurrent apex flows.
const MAX_PENDING_APEX = 16;
const pendingApex = new Map(); // token -> { resolve, reject, timer }

// Phase 5 (#1201) + codex review #1201 cycle 1 finding 4:
// `apex_operations` can be keyed by descriptor name (`tool:`) or by
// class. A typo in the tool name parses successfully but silently
// disables the intended apex gate. We track every descriptor that
// reaches `registerTool` so the server can call
// `validateApexCoverage(policy)` once after all registrations and
// fail closed on a mismatch.
const registeredDescriptorNames = new Set();

// Per-process caches. These are module-level state by design: an MCP
// server runs a single process and the caches are bounded by the
// session lifetime. Tests reset them via `_resetGateCachesForTests()`.
//
// `idempotencyCache` keys are `${tool}:${key}` and store the
// previous result along with the request fingerprint. Reusing the
// same idempotency key with a DIFFERENT non-control payload is a
// programming error and must fail loudly — the wrapper throws
// PolicyError on a fingerprint mismatch within the TTL window
// (codex review #1180 cycle 2 finding 1). Same key + same payload
// returns the cached result; this is the intended retry-storm
// protection.
//
// `idempotencyInFlight` is the concurrent-retry lock: while a
// handler is running, the entry lives in this map so concurrent
// retries with the same `(tool, key)` share that promise instead of
// double-executing the mutation. The entry carries the request
// fingerprint so a concurrent retry with the SAME key but a
// DIFFERENT payload is refused — the protection mirrors the
// completed-cache fingerprint check so the in-flight path doesn't
// silently dedupe against a mismatched payload (codex review #1180
// cycle 3 finding 1).
//
// Expired entries are reaped proactively in `_reapExpiredIdempotency`
// so a long-lived MCP server with many unique keys does not retain
// stale entries indefinitely (codex review #1180 cycle 2 finding 2).
//
// Codex review #1180 cycle 1 finding 4 + cycle 2 findings 1 & 2.
const idempotencyCache = new Map(); // cacheKey -> { ts, result, fingerprint }
const idempotencyInFlight = new Map(); // cacheKey -> { promise, fingerprint }

// Secret handles map a UUID-tagged opaque reference to the raw
// secret bytes. Codex review #1180 cycle 1 finding 5: the previous
// version had no expiry, so a long-lived server would retain raw
// secret material indefinitely. We enforce a TTL on resolve and
// proactively drop expired entries; the in-process resolver is the
// only escape hatch, and only valid callers in this process can
// consume an active handle.
const secretHandles = new Map(); // "shf-secret:<uuid>" -> { value, ts }

export function _resetGateCachesForTests() {
  idempotencyCache.clear();
  idempotencyInFlight.clear();
  secretHandles.clear();
  planStore.clear();
  rateCapWindows.clear();
  for (const entry of pendingApex.values()) {
    if (entry.timer) clearTimeout(entry.timer);
  }
  pendingApex.clear();
  registeredDescriptorNames.clear();
}

/**
 * Validate that every `apex_operations[*].tool` rule in the active
 * policy corresponds to a descriptor that actually reached
 * `registerTool`. Intended to be called from the server entrypoint
 * once after every `registerTool` has run. Fails closed if a typo
 * in `.shifter.yaml` would silently disable the intended apex gate.
 *
 * Codex review #1201 cycle 1 finding 4.
 */
export function validateApexCoverage(policy) {
  for (const rule of policy.apexOperations()) {
    if (rule.tool && !registeredDescriptorNames.has(rule.tool)) {
      throw new PolicyError(
        `policy: apex_operations references tool '${rule.tool}' which is not a registered descriptor`,
      );
    }
  }
}

function _canonicalJson(value) {
  // Stable JSON serialization for the idempotency fingerprint: keys
  // sorted, no whitespace. Arrays keep order; primitive types
  // pass through. The result is fed into sha256 so we don't worry
  // about huge args bloating the cache key.
  if (value === null || value === undefined) return "null";
  if (typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) {
    return "[" + value.map((v) => _canonicalJson(v)).join(",") + "]";
  }
  const keys = Object.keys(value).sort((a, b) => a.localeCompare(b));
  return (
    "{" +
    keys.map((k) => JSON.stringify(k) + ":" + _canonicalJson(value[k])).join(",") +
    "}"
  );
}

// Control args injected by the wrapper / consumed by gates rather
// than by the underlying handler. Stripped from the args passed to
// the handler and excluded from the idempotency fingerprint.
//
// Phase 2's `execute` flag was the dry-run/real-run toggle — it
// belongs here. Phase 3 replaces that mechanism with two-phase
// plan/execute registration, so the wrapper-control role of
// `execute` is gone. `execute` is back to being a free domain arg
// (e.g. `reconcile_ranges` uses it to gate its own internal
// preview-vs-mutate path), and the wrapper must NOT strip it from
// handler args.
const WRAPPER_CONTROL_KEYS = [
  "idempotency_key",
  "confirm_env",
  "acknowledge_untrusted_input",
  "plan_id",
];

function _fingerprintArgs(args) {
  if (!args || typeof args !== "object") return _canonicalJson(args ?? null);
  const fingerprintArgs = { ...args };
  for (const key of WRAPPER_CONTROL_KEYS) delete fingerprintArgs[key];
  return createHash("sha256").update(_canonicalJson(fingerprintArgs)).digest("hex");
}

function _stripWrapperControlArgs(args) {
  if (!args || typeof args !== "object") return args;
  const handlerArgs = { ...args };
  for (const key of WRAPPER_CONTROL_KEYS) delete handlerArgs[key];
  return handlerArgs;
}

// Description redaction phrase, used when a class declares
// `description_redaction: true`. Replacing the entire description is
// stricter than phrase-stripping (and easier to reason about): it
// guarantees no bypass procedure language can leak via `list_tools`.
const REDACTED_DESCRIPTION =
  "[description redacted per ADR-014-R6 — operator agent tool]";

// Every gate helper reads the resolved tool policy
// (`Policy.resolveToolPolicy(name, klass)`) instead of the raw
// class defaults. `resolveToolPolicy` already merges
// `class_defaults[klass]` with any `tools[name].overrides`, so
// per-tool tunings declared in `.shifter.yaml` (e.g. tightening a
// single named_db_write tool's idempotency requirement, or relaxing
// a particular dev_bypass_tunnel `allowed_envs`) are honored by every
// gate without each helper having to merge separately.
//
// Codex review #1180 cycle 1 finding 3.
function _toolPolicy(descriptor, policy) {
  return policy.resolveToolPolicy(descriptor.name, descriptor.klass);
}

function _isRedactedClass(descriptor, policy) {
  return _toolPolicy(descriptor, policy).description_redaction === true;
}

function _maybeRedactDescription(rawDescription, descriptor, policy) {
  if (!_isRedactedClass(descriptor, policy)) return rawDescription ?? "";
  return REDACTED_DESCRIPTION;
}

function _enforceEnvPolicy(args, descriptor, policy) {
  // Two checks compose under "env policy":
  //
  // (a) When `policy.envProdRequiresConfirm()` is true and the call
  //     targets prod, the caller MUST also pass
  //     `confirm_env="prod"`. This stops single-arg fat-fingers
  //     from running a prod-destructive op by accident.
  //
  // (b) Classes with an `allowed_envs` list (today only
  //     `dev_bypass_tunnel`) refuse calls whose env is outside
  //     that list. This is the ADR-014-R5 "no implicit prod"
  //     control.
  const env = args?.env;
  if (env === "prod" && policy.envProdRequiresConfirm()) {
    if (args?.confirm_env !== "prod") {
      throw new PolicyError(
        `${descriptor.name}: env="prod" requires confirm_env="prod"`,
      );
    }
  }
  const allowedEnvs = _toolPolicy(descriptor, policy).allowed_envs;
  if (allowedEnvs && env !== undefined && env !== null) {
    if (!allowedEnvs.includes(env)) {
      throw new PolicyError(
        `${descriptor.name}: env "${env}" is not in allowed_envs ${JSON.stringify(allowedEnvs)}`,
      );
    }
  }
}

// ===========================================================================
// Phase 4 (#1200): untrusted-input fencing.
//
// Producers (tools whose handler returns free-form text sourced from
// outside the operator's own trust boundary — log streams, S3 object
// bodies, SSM stdout, future web fetches) declare a small static
// source label in their descriptor. The wrapper post-processes the
// handler's text return and embeds it inside an
// `[UNTRUSTED:<source>:BEGIN] ... [UNTRUSTED:<source>:END]` fence so
// the LLM can recognize that subsequent text is attacker-controllable.
//
// Consumers (tools whose handler accepts free-form text that becomes
// the operative payload — `query.sql`, `execute.sql`,
// `ssm_send_command.command`, `run_manage_command.command`) declare
// which fields to scan. The wrapper refuses calls whose declared
// fields contain a fence pattern unless
// `acknowledge_untrusted_input: true` is also set, forcing the agent
// to explicitly acknowledge it is acting on text sourced from a
// producer's untrusted output.
// ===========================================================================

const UNTRUSTED_SOURCE_LABEL_RE = /^[a-z][a-z0-9_]{0,31}$/;
// Match a producer fence opener anywhere in the field. The closer is
// allowed to be missing; an opener alone is enough signal that the
// argument carries content from an untrusted producer.
const UNTRUSTED_FENCE_OPENER_RE = /\[UNTRUSTED:[a-z][a-z0-9_]{0,31}:BEGIN]/;

function _validateUntrustedSource(descriptor, policy) {
  const label = descriptor.untrusted_source;
  if (label === undefined) return;
  if (typeof label !== "string" || !UNTRUSTED_SOURCE_LABEL_RE.test(label)) {
    throw new PolicyError(
      `registerTool: tool '${descriptor.name}' has malformed untrusted_source '${label}' (must match ${UNTRUSTED_SOURCE_LABEL_RE})`,
    );
  }
  const allow = policy.untrustedSources();
  // Allowlist is required: if `.shifter.yaml` omits `untrusted_sources`
  // entirely while a descriptor declares one, the contract collapses
  // to "anything goes" — and a typo in the descriptor (or a malicious
  // future descriptor) could relabel the fence without any check.
  // Force the operator to enumerate accepted labels explicitly.
  if (allow.size === 0) {
    throw new PolicyError(
      `registerTool: tool '${descriptor.name}' declares untrusted_source '${label}' but .shifter.yaml has no 'untrusted_sources' allowlist`,
    );
  }
  if (!allow.has(label)) {
    throw new PolicyError(
      `registerTool: tool '${descriptor.name}' has untrusted_source '${label}' not in .shifter.yaml's untrusted_sources allowlist`,
    );
  }
}

// Codex review #1201 cycle 2 finding: a typo in a descriptor's
// `untrusted_inputs` / `sensitive_args` list (e.g. `["sqll"]` on
// `query`) registers cleanly and silently disables the intended
// guardrail. Cross-check every named field against the registered
// schema's keys so misconfigured descriptors fail closed at startup.
function _assertFieldsInSchema(descriptor, listName) {
  const fields = descriptor[listName];
  if (fields === undefined) return;
  if (!Array.isArray(fields) || fields.some((f) => typeof f !== "string" || !f)) {
    throw new PolicyError(
      `registerTool: tool '${descriptor.name}' ${listName} must be an array of non-empty field names`,
    );
  }
  const schemaKeys = new Set(
    Object.keys(
      descriptor.schema && typeof descriptor.schema === "object" ? descriptor.schema : {},
    ),
  );
  for (const field of fields) {
    if (!schemaKeys.has(field)) {
      throw new PolicyError(
        `registerTool: tool '${descriptor.name}' ${listName}[*]='${field}' is not a key of descriptor.schema`,
      );
    }
  }
}

function _validateUntrustedInputs(descriptor) {
  _assertFieldsInSchema(descriptor, "untrusted_inputs");
}

function _validateSensitiveArgs(descriptor) {
  _assertFieldsInSchema(descriptor, "sensitive_args");
}

function _enforceUntrustedInputGate(args, descriptor) {
  const fields = descriptor.untrusted_inputs;
  if (!fields || fields.length === 0) return;
  if (args?.acknowledge_untrusted_input === true) return;
  for (const field of fields) {
    const value = args?.[field];
    if (typeof value === "string" && UNTRUSTED_FENCE_OPENER_RE.test(value)) {
      throw new PolicyError(
        `${descriptor.name}: arg '${field}' contains an untrusted-input fence; set acknowledge_untrusted_input: true to consume it`,
      );
    }
  }
}

// Substring an attacker-controlled producer output cannot be allowed
// to embed verbatim — a literal `[UNTRUSTED:logs:END]` inside a log
// line would visually terminate the fence and let the LLM treat the
// trailing bytes as trusted. Neutralize every `[UNTRUSTED:` in the
// body by replacing the leading bracket-keyword pair with a sentinel
// that preserves the text visually but does not lex as a fence
// boundary. Codex review #1201 cycle 1 finding 7 (security/class).
const UNTRUSTED_BODY_RE = /\[UNTRUSTED:/g;
const UNTRUSTED_BODY_ESCAPE = "[UNTRUSTED-ESC:";

function _escapeUntrustedBody(text) {
  return text.replace(UNTRUSTED_BODY_RE, UNTRUSTED_BODY_ESCAPE);
}

function _wrapUntrustedSource(result, descriptor) {
  const label = descriptor.untrusted_source;
  if (!label) return result;
  if (!result || !Array.isArray(result.content) || result.content.length === 0) {
    return result;
  }
  // Codex review #1201 cycle 2 finding: a multi-item text response
  // would previously leave items beyond content[0] outside the
  // trust-boundary fence even though the whole producer output is
  // by definition untrusted. Wrap every text item individually so
  // the contract — "all text content from this producer is fenced"
  // — holds regardless of how many content items the handler
  // emitted. Non-text items pass through unchanged.
  return {
    ...result,
    content: result.content.map((item) => {
      if (item?.type !== "text" || typeof item?.text !== "string") return item;
      const safeBody = _escapeUntrustedBody(item.text);
      return {
        ...item,
        text: `[UNTRUSTED:${label}:BEGIN]\n${safeBody}\n[UNTRUSTED:${label}:END]`,
      };
    }),
  };
}

// ===========================================================================
// Phase 3 (#1199): per-class sliding-window rate cap.
// ===========================================================================

function _enforceRateCap(args, descriptor, policy) {
  const tp = _toolPolicy(descriptor, policy);
  const cap = tp.rate_cap;
  if (!cap) return;
  const { count, window_seconds } = cap;
  const windowMs = window_seconds * 1000;
  const now = Date.now();
  let arr = rateCapWindows.get(descriptor.klass);
  if (!arr) {
    arr = [];
    rateCapWindows.set(descriptor.klass, arr);
  }
  while (arr.length > 0 && arr[0] <= now - windowMs) {
    arr.shift();
  }
  if (arr.length >= count) {
    throw new PolicyError(
      `${descriptor.name}: rate cap exceeded for class '${descriptor.klass}' (${count} calls per ${window_seconds}s)`,
    );
  }
  arr.push(now);
}

// ===========================================================================
// Phase 3 (#1199): two-phase plan store.
// ===========================================================================

function _reapExpiredPlans() {
  const now = Date.now();
  for (const [id, entry] of planStore) {
    if (now >= entry.expiresAt) planStore.delete(id);
  }
}

function _storePlan(descriptor, args, fingerprint) {
  _reapExpiredPlans();
  if (planStore.size >= MAX_PLAN_STORE_SIZE) {
    // FIFO eviction once the cap is hit even after reaping — Map
    // iteration order is insertion order, so the first key is the
    // oldest. Eviction is fail-closed: the evicted plan_id becomes
    // unknown to subsequent execute_<name> calls.
    const oldest = planStore.keys().next().value;
    if (oldest !== undefined) planStore.delete(oldest);
  }
  const planId = randomUUID();
  const expiresAt = Date.now() + PLAN_TTL_MS;
  planStore.set(planId, {
    tool: descriptor.name,
    klass: descriptor.klass,
    args,
    fingerprint,
    expiresAt,
  });
  return { planId, expiresAt };
}

function _consumePlan(planId, expectedTool, descriptor) {
  if (!planId || typeof planId !== "string") {
    throw new PolicyError(
      `${descriptor.name}: plan_id argument is required`,
    );
  }
  _reapExpiredPlans();
  const entry = planStore.get(planId);
  if (!entry) {
    throw new PolicyError(
      `${descriptor.name}: unknown plan_id (not found, expired, or already consumed)`,
    );
  }
  if (Date.now() >= entry.expiresAt) {
    planStore.delete(planId);
    throw new PolicyError(
      `${descriptor.name}: plan_id expired (60s TTL exceeded)`,
    );
  }
  if (entry.tool !== expectedTool) {
    // Don't reveal cross-tool plan ids; treat mismatched-tool consumption
    // the same as unknown so a probing caller can't enumerate the store.
    throw new PolicyError(
      `${descriptor.name}: unknown plan_id`,
    );
  }
  // Atomic consume: delete BEFORE running the handler so a concurrent
  // execute with the same plan_id sees "unknown" rather than running
  // twice.
  planStore.delete(planId);
  return entry;
}

// ===========================================================================
// Phase 4 (#1200): apex out-of-band operator approval.
// ===========================================================================

function _matchesApexRule(rule, args, descriptor, kind) {
  if (rule.env !== (args?.env ?? null) && rule.env !== args?.env) return false;
  if (rule.operation_kind !== kind) return false;
  if (rule.tool && rule.tool !== descriptor.name) return false;
  if (rule.class && rule.class !== descriptor.klass) return false;
  if (rule.requires_write === true && descriptor.is_write !== true) return false;
  return true;
}

function _isApexCall(args, descriptor, policy, kind) {
  for (const rule of policy.apexOperations()) {
    if (_matchesApexRule(rule, args, descriptor, kind)) return true;
  }
  return false;
}

async function _enforceApexApproval(args, descriptor, policy, kind, auditExtras = {}) {
  if (!_isApexCall(args, descriptor, policy, kind)) return false;
  // Bounded queue check: refuse new apex requests when the operator
  // already has the cap's worth of unconfirmed prompts. Throwing
  // here flows into _runHandlerAndPostGates's catch path, which
  // audits the refusal as result_class:'error'.
  if (pendingApex.size >= MAX_PENDING_APEX) {
    throw new PolicyError(
      `${descriptor.name}: apex pending-approval queue is full (${MAX_PENDING_APEX} prompts awaiting operator confirmation)`,
    );
  }
  const token = randomBytes(APEX_TOKEN_BYTES).toString("hex");
  const env = args?.env ?? null;
  // Codex review #1201 cycle 1 finding 5: audit the awaiting-approval
  // event so the operator can distinguish an apex-approved execution
  // from a non-apex execution in the JSONL audit, and so the policy
  // facts (tool, class, env, profile) for the apex prompt are durably
  // recorded. The token itself is NEVER emitted to audit — only the
  // structural fact that an apex prompt was raised.
  //
  // Cycle 2 finding "Execute-side audit events lose plan correlation":
  // thread plan_id (when present) into the awaiting_approval record
  // so the apex prompt event ties back to the plan that triggered it.
  _writeAudit(policy, descriptor, args, Date.now(), {
    result_class: "awaiting_approval",
    apex: true,
    plan_id: auditExtras.plan_id,
  });
  // Stderr-only emission: never goes to MCP responses, audit args, or
  // error envelopes. The fence around env value avoids accidentally
  // emitting a multi-line stderr line if an attacker-controlled env
  // somehow reached this point (it can't through the Zod schema, but
  // defense in depth).
  process.stderr.write(
    `[apex-approval] ${descriptor.name} env=${JSON.stringify(env)} kind=${kind} token=${token} ttl=${APEX_APPROVAL_TTL_MS / 1000}s — call 'approve' with this token to release\n`,
  );
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pendingApex.delete(token);
      reject(
        new PolicyError(
          `${descriptor.name}: apex approval timeout (no operator confirmation within ${APEX_APPROVAL_TTL_MS / 1000}s)`,
        ),
      );
    }, APEX_APPROVAL_TTL_MS);
    pendingApex.set(token, { resolve, reject, timer });
  });
  // Apex passed — signal back so the caller marks the final audit
  // record with `apex: true`.
  return true;
}

/**
 * Consume a pending apex approval token. Returns `true` when the
 * token matched an active pending request (releasing the parked
 * handler) or `false` when the token is unknown / already consumed /
 * expired. Single-use: the entry is deleted as part of the consume,
 * so a duplicate `approve` call returns `false`.
 *
 * Intended caller: the `approve` MCP tool registered on the server.
 */
export function consumeApexToken(token) {
  if (typeof token !== "string" || token.length === 0) return false;
  const entry = pendingApex.get(token);
  if (!entry) return false;
  if (entry.timer) clearTimeout(entry.timer);
  pendingApex.delete(token);
  entry.resolve();
  return true;
}

function _idempotencyState(args, descriptor, policy) {
  const tp = _toolPolicy(descriptor, policy);
  if (tp.idempotency_key !== "required") return { required: false };
  const key = args?.idempotency_key;
  if (!key || typeof key !== "string") {
    throw new PolicyError(
      `${descriptor.name}: idempotency_key argument is required for class '${descriptor.klass}'`,
    );
  }
  // Cache key is `(tool, idempotency_key)`. The non-control args
  // are hashed into a fingerprint that's stored as cache metadata.
  // - Same key + same fingerprint within TTL → return cached result.
  // - Same key + DIFFERENT fingerprint within TTL → reject as a
  //   programming error (codex review #1180 cycle 2 finding 1).
  // - Key not seen / cache expired → execute fresh.
  const fingerprint = _fingerprintArgs(args);
  const cacheKey = `${descriptor.name}:${key}`;
  const cached = idempotencyCache.get(cacheKey);
  if (cached && Date.now() - cached.ts < IDEMPOTENCY_TTL_MS) {
    if (cached.fingerprint !== fingerprint) {
      throw new PolicyError(
        `${descriptor.name}: idempotency_key '${key}' was previously used with different args; refuse to double-mutate`,
      );
    }
    return {
      required: true,
      cached: true,
      result: cached.result,
      cacheKey,
      key,
      fingerprint,
    };
  }
  return { required: true, cached: false, cacheKey, key, fingerprint };
}

function _reapExpiredIdempotency() {
  // Best-effort sweep: drop entries past the TTL so a long-lived
  // server doesn't retain one cached entry per key indefinitely
  // (codex review #1180 cycle 2 finding 2). Correctness is still
  // enforced inside _idempotencyState's TTL window check; this loop
  // is the size-bound guarantee.
  const now = Date.now();
  for (const [k, entry] of idempotencyCache) {
    if (now - entry.ts >= IDEMPOTENCY_TTL_MS) {
      idempotencyCache.delete(k);
    }
  }
}

function _isSecretHandleClass(descriptor, policy) {
  return _toolPolicy(descriptor, policy).return_mode === "handle";
}

function _extractRawSecretText(result) {
  // The convention: secret_handle tools return the raw secret as
  // result.content[0].text. If the shape diverges (no content array,
  // or non-text type), the handle still wraps `result` verbatim but
  // resolveSecretHandle returns the structured value. This is the
  // narrow case the wrap is designed for; tools that need richer
  // returns should be re-classed away from secret_handle.
  if (result && Array.isArray(result.content) && result.content.length > 0) {
    const first = result.content[0];
    if (first?.type === "text" && typeof first?.text === "string") {
      return first.text;
    }
  }
  return result;
}

function _wrapSecretReturn(result, descriptor, policy) {
  if (!_isSecretHandleClass(descriptor, policy)) return result;
  // Codex review #1201 cycle 3 finding 2: pass error envelopes through
  // unmodified. The handler-level convention is `return { content:
  // [{text: "Error: ..."}], isError: true }`; wrapping that into an
  // opaque handle would mask AWS / lookup failures as apparently-
  // successful handle responses AND would be audited as success.
  // Leaving isError envelopes alone lets _runHandlerAndPostGates'
  // handlerReturnedError check fire correctly.
  if (result?.isError === true) return result;
  const raw = _extractRawSecretText(result);
  const handle = `shf-secret:${randomUUID()}`;
  secretHandles.set(handle, { value: raw, ts: Date.now() });
  return {
    content: [{ type: "text", text: handle }],
  };
}

/**
 * Resolve a secret handle back to its raw value. Intended for
 * in-process callers (e.g. the DB pool's `fetchCredentials`) that
 * need the underlying secret to perform work; MCP clients never
 * receive raw values. Throws if the handle is unknown or expired.
 *
 * Expired entries are deleted from the map on every resolve attempt,
 * so a long-lived server doesn't accumulate stale secret bytes
 * indefinitely. Codex review #1180 cycle 1 finding 5.
 */
export function resolveSecretHandle(handle) {
  const entry = secretHandles.get(handle);
  if (!entry) {
    throw new PolicyError(`resolveSecretHandle: unknown handle '${handle}'`);
  }
  if (Date.now() - entry.ts >= SECRET_HANDLE_TTL_MS) {
    secretHandles.delete(handle);
    throw new PolicyError(`resolveSecretHandle: handle '${handle}' has expired`);
  }
  return entry.value;
}

// Best-effort proactive cleanup: drop expired secret handles on
// every wrap. The TTL check in `resolveSecretHandle` is the
// load-bearing one for correctness; this loop just keeps the Map
// from growing unboundedly on a server that wraps many handles but
// never resolves them.
function _reapExpiredSecretHandles() {
  const now = Date.now();
  for (const [handle, entry] of secretHandles) {
    if (now - entry.ts >= SECRET_HANDLE_TTL_MS) {
      secretHandles.delete(handle);
    }
  }
}

function _resultClass(result, error, opts) {
  if (error) return "error";
  if (opts?.cached) return "cached";
  if (opts?.dryRun) return "dry_run";
  return "success";
}

// Sanitize args for any output the operator or audit log might see.
// Combines:
//   - `audit.redact` from .shifter.yaml (name + suffix classifier)
//   - the descriptor's `untrusted_inputs` field list (free-form
//     operative payloads — raw SQL, raw shell command bodies — that
//     are not "secrets" but MUST NOT appear in plan summaries or
//     audit records per the Phase 3/4 design).
// Codex review #1201 cycle 1 finding 3.
function _safeOutputArgs(args, descriptor, policy) {
  if (args === null || args === undefined) return args;
  const sanitized = sanitizeArgs(args, policy.auditConfig().redact ?? []);
  if (
    sanitized &&
    typeof sanitized === "object" &&
    !Array.isArray(sanitized)
  ) {
    if (Array.isArray(descriptor?.untrusted_inputs)) {
      for (const field of descriptor.untrusted_inputs) {
        if (sanitized[field] !== undefined) {
          sanitized[field] = `<redacted: operative ${field}>`;
        }
      }
    }
    // Codex review #1201 cycle 2: `sensitive_args` is the descriptor
    // escape hatch for fields that aren't free-form operative payloads
    // (handled by untrusted_inputs) and aren't covered by audit.redact's
    // suffix classifier, but still must not appear in plan summaries
    // or audit records. The `approve` tool uses this for its `token`
    // arg — the apex design says the token MUST NEVER appear in audit.
    if (Array.isArray(descriptor?.sensitive_args)) {
      for (const field of descriptor.sensitive_args) {
        if (sanitized[field] !== undefined) {
          sanitized[field] = "<redacted>";
        }
      }
    }
  }
  return sanitized;
}

function _writeAudit(policy, descriptor, args, started, outcome) {
  // Per #1198: audit every invocation. The audit module fails closed
  // (returns ok:false) but never throws out; we don't need a
  // try/catch here.
  //
  // Pre-sanitize args here so the descriptor-specific
  // `untrusted_inputs` redaction folds in alongside the policy-wide
  // `audit.redact` list. `appendAuditRecord` re-runs sanitizeArgs
  // internally — that pass is idempotent on the placeholder strings
  // we've already substituted.
  appendAuditRecord(policy, {
    timestamp: new Date(started).toISOString(),
    tool: descriptor.name,
    class: descriptor.klass,
    env: args?.env ?? null,
    profile: policy.profile,
    args: _safeOutputArgs(args ?? {}, descriptor, policy),
    result_class: outcome.result_class,
    duration_ms: Date.now() - started,
    error_class: outcome.error_class,
    idempotency_key: outcome.idempotency_key,
    apex: outcome.apex,
    plan_id: outcome.plan_id,
  });
}

function _isTwoPhaseClass(descriptor, policy) {
  return _toolPolicy(descriptor, policy).two_phase === true;
}

// Codex review #1201 cycle 1 finding 1: the wrapper-gated control
// fields MUST be visible in the registered MCP schema so agents can
// discover them via `list_tools` and the SDK does not strip them
// before they reach the wrapper. The base schema (the descriptor's
// domain fields) is preserved verbatim; this helper adds policy
// control fields on top.
function _augmentSchemaWithControlKeys(baseSchema, descriptor, policy) {
  const augmented = { ...(baseSchema ?? {}) };
  const tp = _toolPolicy(descriptor, policy);
  if (policy.envProdRequiresConfirm()) {
    augmented.confirm_env = z
      .literal("prod")
      .optional()
      .describe(
        'Set to "prod" to confirm a prod-environment call (required when env="prod").',
      );
  }
  if (tp.idempotency_key === "required") {
    augmented.idempotency_key = z
      .string()
      .min(1)
      .optional()
      .describe(
        "Idempotency key — reusing the same key for 15 minutes returns the cached result.",
      );
  }
  if (
    Array.isArray(descriptor.untrusted_inputs) &&
    descriptor.untrusted_inputs.length > 0
  ) {
    augmented.acknowledge_untrusted_input = z
      .boolean()
      .optional()
      .describe(
        "Set to true to consume free-form text containing [UNTRUSTED:<src>] fences sourced from producer tools.",
      );
  }
  return augmented;
}

// Audit helper for the planned/cached/success branches; keeps the
// wrapper bodies linear instead of repeating the audit call shape.
function _audit(policy, descriptor, args, started, outcome) {
  _writeAudit(policy, descriptor, args, started, outcome);
}

// Execute-time gate composition. Runs the side-effect gates that
// must NOT fire at plan time: rate-cap, apex approval, idempotency,
// the handler, the secret-handle wrap, and the untrusted-input
// producer fence wrap. Used by both the direct path (non-two-phase
// classes) and the execute_<name> path (two-phase classes replaying
// stored plan args).
//
// `descriptor` is the original Phase 5 descriptor — it carries the
// stable name used for tool-policy lookups in `.shifter.yaml`
// (`tools.<name>.overrides`). `auditDescriptor` controls the
// audit record's `tool` field: for two-phase classes this is
// `execute_<name>` so the audit log distinguishes the plan-time and
// execute-time records, while resolveToolPolicy keeps targeting the
// underlying tool's class-defaults block.
async function _runHandlerAndPostGates(
  args,
  descriptor,
  auditDescriptor,
  policy,
  kind,
  started,
  auditExtras = {},
) {
  const planId = auditExtras.plan_id;
  // Pre-handler gates that DO consume capacity / require operator
  // attention. Idempotency check happens BEFORE rate-cap and apex so
  // a retried call returns the cached result without re-asking the
  // operator and without consuming a fresh rate-cap slot.
  const idem = _idempotencyState(args, descriptor, policy);
  if (idem.cached) {
    _audit(policy, auditDescriptor, args, started, {
      result_class: "cached",
      idempotency_key: idem.key,
      plan_id: planId,
    });
    return idem.result;
  }
  if (idem.required) {
    const inFlight = idempotencyInFlight.get(idem.cacheKey);
    if (inFlight) {
      if (inFlight.fingerprint !== idem.fingerprint) {
        throw new PolicyError(
          `${descriptor.name}: idempotency_key '${idem.key}' is in flight with different args; refuse to double-mutate`,
        );
      }
      const result = await inFlight.promise;
      _audit(policy, auditDescriptor, args, started, {
        result_class: "cached",
        idempotency_key: idem.key,
        plan_id: planId,
      });
      return result;
    }
  }

  _enforceRateCap(args, descriptor, policy);
  const apexApproved = await _enforceApexApproval(
    args,
    descriptor,
    policy,
    kind,
    { plan_id: planId },
  );

  _reapExpiredSecretHandles();
  _reapExpiredIdempotency();

  const handlerArgs = _stripWrapperControlArgs(args);
  const handlerPromise = (async () => {
    const result = await descriptor.handler(handlerArgs);
    const fenced = _wrapUntrustedSource(result, descriptor);
    return _wrapSecretReturn(fenced, descriptor, policy);
  })();
  if (idem.required) {
    idempotencyInFlight.set(idem.cacheKey, {
      promise: handlerPromise,
      fingerprint: idem.fingerprint,
    });
  }
  let wrappedResult;
  try {
    wrappedResult = await handlerPromise;
  } finally {
    if (idem.required) {
      idempotencyInFlight.delete(idem.cacheKey);
    }
  }
  if (idem.required) {
    idempotencyCache.set(idem.cacheKey, {
      ts: Date.now(),
      result: wrappedResult,
      fingerprint: idem.fingerprint,
    });
  }
  // Codex review #1201 cycle 2: a handler that signals failure by
  // returning `{isError: true}` (the convention shifter-ops uses
  // throughout its handler bodies via `err()`) was previously audited
  // as `success`. Honor isError as an error result class so audit
  // observability matches what the MCP client actually saw.
  const handlerReturnedError = wrappedResult?.isError === true;
  _audit(policy, auditDescriptor, args, started, {
    result_class: handlerReturnedError ? "error" : "success",
    error_class: handlerReturnedError ? "HandlerReturnedError" : undefined,
    idempotency_key: idem.key,
    apex: apexApproved || undefined,
    plan_id: planId,
  });
  return wrappedResult;
}

// Direct-execution wrapper: used for non-two-phase classes. The
// wrapper runs the no-side-effect gates (env policy, untrusted-input
// scan) then `_runHandlerAndPostGates` does the rest.
function _buildDirectHandler(descriptor, policy) {
  return async (args) => {
    const started = Date.now();
    try {
      _enforceUntrustedInputGate(args, descriptor);
      _enforceEnvPolicy(args, descriptor, policy);
      return await _runHandlerAndPostGates(
        args,
        descriptor,
        descriptor,
        policy,
        "direct",
        started,
      );
    } catch (err) {
      _audit(policy, descriptor, args, started, {
        result_class: "error",
        error_class: err?.name ?? "Error",
      });
      throw err;
    }
  };
}

// Plan-side wrapper: enforces no-side-effect gates and stores the
// caller's verbatim args, then returns a small preview the agent
// hands to the matching execute_<name>. The handler is NEVER run
// from this path.
function _buildPlanHandler(descriptor, policy) {
  const planToolName = `plan_${descriptor.name}`;
  const planDescriptor = { ...descriptor, name: planToolName };
  return async (args) => {
    const started = Date.now();
    try {
      _enforceUntrustedInputGate(args, descriptor);
      _enforceEnvPolicy(args, descriptor, policy);
      const fingerprint = _fingerprintArgs(args);
      const { planId, expiresAt } = _storePlan(descriptor, args, fingerprint);
      // Per Phase 3 design and codex review #1201 cycle 1 finding 3:
      // plan summaries must not echo raw SQL/command bodies. Use the
      // descriptor-aware sanitizer so `untrusted_inputs` fields are
      // replaced with placeholder strings even though they pass the
      // plain audit.redact classifier.
      const summary = {
        tool: descriptor.name,
        class: descriptor.klass,
        env: args?.env ?? null,
        args: _safeOutputArgs(args, descriptor, policy),
        expires_at: new Date(expiresAt).toISOString(),
      };
      _audit(policy, planDescriptor, args, started, {
        result_class: "planned",
        plan_id: planId,
      });
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({ plan_id: planId, summary, ttl_seconds: 60 }),
          },
        ],
      };
    } catch (err) {
      // plan-time error: no plan_id has been issued yet (planId is
      // scoped inside the try-block above), so this audit naturally
      // carries no plan_id correlation. Args here are the caller's
      // request and may include the operative payload — sanitization
      // happens inside _writeAudit via _safeOutputArgs.
      _audit(policy, planDescriptor, args, started, {
        result_class: "error",
        error_class: err?.name ?? "Error",
      });
      throw err;
    }
  };
}

// Execute-side wrapper: consumes a plan_id, replays its stored args
// through the side-effect gates, runs the handler. The caller's
// non-plan_id args are ignored (the plan is the single source of
// truth for what runs).
//
// Codex review #1201 cycle 2: every execute-side audit record must
// carry the consumed plan_id so events tie back to the plan. The
// error path also uses the STORED plan args (when consumed
// successfully) rather than the transient `{plan_id}` call args, so
// errors after plan consumption still record env/profile/sanitized
// payload — not `null` env and an empty payload.
function _buildExecuteHandler(descriptor, policy) {
  const execToolName = `execute_${descriptor.name}`;
  const execDescriptor = { ...descriptor, name: execToolName };
  return async (args) => {
    const started = Date.now();
    const planId = args?.plan_id;
    let entry = null;
    try {
      entry = _consumePlan(planId, descriptor.name, execDescriptor);
      // The stored args have already passed env policy + untrusted-input
      // scan at plan time. Re-running env policy here is redundant but
      // cheap; re-running the untrusted-input scan would be wrong (an
      // acknowledged fence is already locked in to the plan). We skip
      // both at the execute side and proceed straight to the
      // side-effect gates.
      return await _runHandlerAndPostGates(
        entry.args,
        descriptor,
        execDescriptor,
        policy,
        "execute",
        started,
        { plan_id: planId },
      );
    } catch (err) {
      const auditArgs = entry?.args ?? args ?? {};
      _audit(policy, execDescriptor, auditArgs, started, {
        result_class: "error",
        error_class: err?.name ?? "Error",
        plan_id: planId,
      });
      throw err;
    }
  };
}

// Register an MCP tool under the policy layer. Tools whose class is
// not in the active session profile are NOT registered at all — they
// don't appear in `list_tools`. Tools without a class tag, or with a
// class the policy did not declare, fail closed.
//
// For classes where `class_defaults.<class>.two_phase: true`
// (`infra_mutation`, `ssm_arbitrary`, `db_arbitrary` in the shipped
// policy), the wrapper registers a PAIR of MCP tools:
//   - plan_<name>(args)       — returns {plan_id, summary, ttl_seconds}
//   - execute_<name>(plan_id) — runs the stored handler args, gated
//                                by rate-cap + apex approval + idempotency
// For non-two-phase classes the wrapper registers the original
// `<name>` with the side-effect gates composed directly.
export function registerTool(ctx, descriptor) {
  const { server, policy } = ctx;
  if (!server || typeof server.tool !== "function") {
    throw new PolicyError("registerTool: ctx.server is required");
  }
  if (!policy || !(policy instanceof Policy)) {
    throw new PolicyError("registerTool: ctx.policy must be a Policy instance");
  }
  if (!descriptor || typeof descriptor !== "object") {
    throw new PolicyError("registerTool: descriptor is required");
  }
  const { name, klass, description, schema, handler } = descriptor;
  if (!name || typeof name !== "string") {
    throw new PolicyError("registerTool: descriptor.name is required");
  }
  if (!klass || typeof klass !== "string") {
    throw new PolicyError(
      `registerTool: descriptor.klass is required (tool '${name}')`,
    );
  }
  if (!policy.classDeclared(klass)) {
    throw new PolicyError(
      `registerTool: tool '${name}' has unknown class '${klass}'`,
    );
  }
  if (typeof handler !== "function") {
    throw new PolicyError(
      `registerTool: descriptor.handler must be a function (tool '${name}')`,
    );
  }

  // Phase 4 descriptor-time validation: catches malformed
  // `untrusted_source` labels and `untrusted_inputs` / `sensitive_args`
  // field lists before the tool reaches the registry. Done
  // unconditionally (not gated on classEnabled) so misconfigured
  // descriptors are caught even when a profile excludes the class
  // today.
  _validateUntrustedSource(descriptor, policy);
  _validateUntrustedInputs(descriptor);
  _validateSensitiveArgs(descriptor);

  // Record every descriptor that survives validation, regardless of
  // whether the active profile registers it as a live tool, so the
  // apex-coverage check (codex #1201 cycle 1 finding 4) can detect
  // typos against the full canonical descriptor set rather than just
  // the active subset.
  registeredDescriptorNames.add(name);

  // Codex review #1201 cycle 3 finding 3: under Phase 3 the dry-run
  // gate is gone — execution-default is enforced only via the
  // two-phase plan_/execute_ pair. A resolved tool policy of
  // `{execute_default: false, two_phase: !== true}` would run with
  // no preview at all (the direct handler executes immediately),
  // which silently contradicts what the config says. Fail closed
  // rather than letting `execute_default: false` become a no-op.
  const _tp = _toolPolicy(descriptor, policy);
  if (_tp.execute_default === false && _tp.two_phase !== true) {
    throw new PolicyError(
      `registerTool: tool '${name}' resolves to execute_default:false without two_phase:true — the dry-run preview is enforced only by the two-phase wrapper, so this combination has no runtime effect`,
    );
  }

  if (!policy.classEnabled(klass)) {
    return { registered: false, reason: "class-disabled" };
  }

  const finalDescription = _maybeRedactDescription(description, descriptor, policy);

  const augmentedSchema = _augmentSchemaWithControlKeys(schema, descriptor, policy);

  if (_isTwoPhaseClass(descriptor, policy)) {
    const planHandler = _buildPlanHandler(descriptor, policy);
    const execHandler = _buildExecuteHandler(descriptor, policy);
    // plan_<name> exposes the descriptor's domain fields PLUS the
    // policy control fields the wrapper requires (confirm_env,
    // idempotency_key, acknowledge_untrusted_input — whichever
    // apply). execute_<name> takes only { plan_id }; the stored plan
    // carries the control fields from the plan_<name> call.
    server.tool(
      `plan_${name}`,
      finalDescription
        ? `[plan] ${finalDescription}`
        : `[plan] ${name}`,
      augmentedSchema,
      planHandler,
    );
    server.tool(
      `execute_${name}`,
      finalDescription
        ? `[execute] ${finalDescription}`
        : `[execute] ${name}`,
      {
        plan_id: z
          .string()
          .min(1)
          .describe("plan_id returned by the matching plan_<name> call"),
      },
      execHandler,
    );
    return { registered: true, twoPhase: true };
  }

  const directHandler = _buildDirectHandler(descriptor, policy);
  server.tool(name, finalDescription, augmentedSchema, directHandler);
  return { registered: true, twoPhase: false };
}
