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
import { createHash, randomUUID } from "node:crypto";
import yaml from "yaml";
import { z } from "zod";
import { appendAuditRecord } from "./audit.js";

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

function _fingerprintArgs(args) {
  // The idempotency_key and the execute control flag are excluded
  // from the fingerprint: re-running a write with `execute=true`
  // after a dry-run with the same `idempotency_key` would otherwise
  // bypass the cache. Everything else in `args` (including `env`,
  // the SQL payload, etc.) participates so a mismatched retry is
  // detected.
  if (!args || typeof args !== "object") return _canonicalJson(args ?? null);
  const fingerprintArgs = { ...args };
  delete fingerprintArgs.idempotency_key;
  delete fingerprintArgs.execute;
  delete fingerprintArgs.confirm_env;
  return createHash("sha256").update(_canonicalJson(fingerprintArgs)).digest("hex");
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

function _shouldDryRun(args, descriptor, policy) {
  const tp = _toolPolicy(descriptor, policy);
  if (tp.execute_default !== false) return false;
  return args?.execute !== true;
}

function _dryRunPreview(args, descriptor) {
  // The preview is deliberately small: it tells the agent what would
  // happen without actually running. Sanitization of `args` happens
  // at audit time; here we just echo the agent's request back.
  const previewArgs = args ? { ...args } : {};
  delete previewArgs.execute;
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify({
          dry_run: true,
          tool: descriptor.name,
          klass: descriptor.klass,
          would_execute_with: previewArgs,
          note: "Pass execute=true to actually run this tool.",
        }),
      },
    ],
  };
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

function _writeAudit(policy, descriptor, args, started, outcome) {
  // Per #1198: audit every invocation. The audit module fails closed
  // (returns ok:false) but never throws out; we don't need a
  // try/catch here.
  appendAuditRecord(policy, {
    timestamp: new Date(started).toISOString(),
    tool: descriptor.name,
    class: descriptor.klass,
    env: args?.env ?? null,
    profile: policy.profile,
    args: args ?? {},
    result_class: outcome.result_class,
    duration_ms: Date.now() - started,
    error_class: outcome.error_class,
    idempotency_key: outcome.idempotency_key,
  });
}

// Register an MCP tool under the policy layer. Tools whose class is
// not in the active session profile are NOT registered at all — they
// don't appear in `list_tools`. Tools without a class tag, or with a
// class the policy did not declare, fail closed.
//
// Phase 2 (#1198) composes env-policy / dry-run / description-
// redaction / idempotency / secret-handle gates and a per-call
// audit append around the handler. Phase 5 (#1201) is what wires the
// 45 tools in `index.js` through `registerTool`; until then the
// gates exist at the seam but the live server still bypasses them.
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
  if (!policy.classEnabled(klass)) {
    return { registered: false, reason: "class-disabled" };
  }

  const finalDescription = _maybeRedactDescription(description, descriptor, policy);

  const wrapped = async (args) => {
    const started = Date.now();
    let outcome;
    try {
      _enforceEnvPolicy(args, descriptor, policy);
      const idem = _idempotencyState(args, descriptor, policy);
      if (idem.cached) {
        outcome = {
          result_class: _resultClass(idem.result, null, { cached: true }),
          idempotency_key: idem.key,
        };
        _writeAudit(policy, descriptor, args, started, outcome);
        return idem.result;
      }
      // In-flight retry protection (codex review #1180 cycle 1
      // finding 4 + cycle 3 finding 1): if a concurrent call with
      // the SAME `(tool, key)` is already running, share its promise
      // — unless the fingerprints differ, in which case refuse the
      // mismatched concurrent retry the same way the completed-cache
      // path does.
      if (idem.required) {
        const inFlight = idempotencyInFlight.get(idem.cacheKey);
        if (inFlight) {
          if (inFlight.fingerprint !== idem.fingerprint) {
            throw new PolicyError(
              `${descriptor.name}: idempotency_key '${idem.key}' is in flight with different args; refuse to double-mutate`,
            );
          }
          const result = await inFlight.promise;
          outcome = {
            result_class: _resultClass(result, null, { cached: true }),
            idempotency_key: idem.key,
          };
          _writeAudit(policy, descriptor, args, started, outcome);
          return result;
        }
      }
      if (_shouldDryRun(args, descriptor, policy)) {
        const preview = _dryRunPreview(args, descriptor);
        outcome = { result_class: "dry_run" };
        _writeAudit(policy, descriptor, args, started, outcome);
        return preview;
      }

      _reapExpiredSecretHandles();
      _reapExpiredIdempotency();

      // Wrap the handler call in a Promise we can park in
      // idempotencyInFlight so concurrent retries observe it. The
      // Promise is removed from the in-flight map in `finally` so
      // failures don't leave stale entries.
      const handlerPromise = (async () => {
        const result = await handler(args);
        return _wrapSecretReturn(result, descriptor, policy);
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
      outcome = {
        result_class: "success",
        idempotency_key: idem.key,
      };
      _writeAudit(policy, descriptor, args, started, outcome);
      return wrappedResult;
    } catch (err) {
      outcome = {
        result_class: "error",
        error_class: err?.name ?? "Error",
      };
      _writeAudit(policy, descriptor, args, started, outcome);
      throw err;
    }
  };

  server.tool(name, finalDescription, schema ?? {}, wrapped);
  return { registered: true };
}
