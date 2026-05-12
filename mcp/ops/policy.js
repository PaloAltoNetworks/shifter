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
import yaml from "yaml";
import { z } from "zod";

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
export function parsePolicy(raw, opts = {}) {
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
  const declaredClasses = new Set(raw.classes);

  // class_defaults MUST have an entry for every declared class, and
  // MUST NOT have entries for undeclared classes. Each entry MUST be
  // an object (even if empty). The wrapper depends on every
  // declared class having a defaults block; a silent {} fallback
  // would let a future class slip in without gates wired up.
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
    // Strict-shape validation per class_defaults entry. Catches
    // typos like `rate_cap: { count: 'three' }` or unknown keys.
    _zodValidate(`class_defaults.${klass}`, ClassDefaultsValueSchema, cd[klass]);
  }
  for (const key of Object.keys(cd)) {
    if (!declaredClasses.has(key)) {
      throw new PolicyError(
        `policy: 'class_defaults' has entry for '${key}', which is not in 'classes'`,
      );
    }
  }

  // Cross-validate: any `class_defaults.<k>.allowed_envs` entry must
  // contain `environments.default` so the default env is always
  // permitted (otherwise the default env would refuse the call).
  // Deferred until environments is validated below.

  // Environments: strict shape. The default env must be one of
  // dev/prod and prod_requires_confirm must be boolean. A typo like
  // `prod_requires_confirm: 'true'` (string) would otherwise be
  // truthy-but-not-=== true, and `envProdRequiresConfirm()` would
  // return false — silently weakening the gate.
  _zodValidate("environments", EnvironmentsSchema, raw.environments);

  // Audit: strict shape. A missing `redact:` list, a non-boolean
  // `enabled`, or a non-string `path` are all fail-closed conditions.
  _zodValidate("audit", AuditSchema, raw.audit);

  // Tools: per-tool override map (may be empty / absent). Each entry
  // is strict-shaped so a typo doesn't bypass the policy.
  if ("tools" in raw) {
    if (raw.tools === null) {
      // explicit null is fine — same as absent
    } else if (typeof raw.tools !== "object" || Array.isArray(raw.tools)) {
      throw new PolicyError("policy: 'tools' must be an object (or omitted)");
    } else {
      _zodValidate("tools", ToolsMapSchema, raw.tools);
      for (const [toolName, override] of Object.entries(raw.tools)) {
        if (override.class !== undefined && !declaredClasses.has(override.class)) {
          throw new PolicyError(
            `policy: 'tools.${toolName}.class' is '${override.class}', which is not in 'classes'`,
          );
        }
      }
    }
  }

  const sp = raw.session_profile;
  if (!sp || typeof sp !== "object" || !sp.profiles || typeof sp.profiles !== "object") {
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

  const activeProfileName = opts.profile ?? sp.default;
  if (!activeProfileName || !sp.profiles[activeProfileName]) {
    throw new PolicyError(`policy: unknown active profile '${activeProfileName}'`);
  }

  // Final layer: enforce ADR-014-R5/R6 semantic invariants. Shape
  // checks above don't catch a config that's structurally valid but
  // weakens the boundary (e.g. infra_mutation with execute_default:
  // true).
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

// Register an MCP tool under the policy layer. Tools whose class is
// not in the active session profile are NOT registered at all — they
// don't appear in `list_tools`. Tools without a class tag, or with a
// class the policy did not declare, fail closed.
//
// Phase 1 wires only class/profile gating. Subsequent phases compose
// env policy, dry-run, audit, idempotency, two-phase, etc. on top of
// this same entrypoint.
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
  server.tool(name, description ?? "", schema ?? {}, handler);
  return { registered: true };
}
