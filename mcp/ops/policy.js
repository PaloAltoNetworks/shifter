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
// This module is the composition root of the policy layer: it wires
// the config parser (policy-config.js), the shared gate state
// (policy-gate-state.js), and the individual gate modules
// (policy-fingerprint / policy-untrusted / policy-audit /
// policy-tool-policy / policy-gates) into the two-phase and direct
// handler wrappers and the public `registerTool` seam. The file was
// split out of a single large module to satisfy javascript:S104; the
// public API and runtime behavior are unchanged, and every name
// previously importable from `./policy.js` is re-exported below.
//
// See docs/architecture/mcp-ops-privileged-surface-preflight-777.md
// for the threat model and mcp/ops/SECURITY.md for the operational
// rules.

import { z } from "zod";

import { PolicyError, Policy } from "./policy-config.js";
import {
  idempotencyCache,
  idempotencyInFlight,
  registeredDescriptorNames,
} from "./policy-gate-state.js";
import {
  _fingerprintArgs,
  _stripWrapperControlArgs,
} from "./policy-fingerprint.js";
import {
  _validateUntrustedSource,
  _validateUntrustedInputs,
  _validateSensitiveArgs,
  _enforceUntrustedInputGate,
  _wrapUntrustedSource,
} from "./policy-untrusted.js";
import { _audit, _safeOutputArgs } from "./policy-audit.js";
import {
  _toolPolicy,
  _maybeRedactDescription,
  _enforceEnvPolicy,
  _isTwoPhaseClass,
  _augmentSchemaWithControlKeys,
} from "./policy-tool-policy.js";
import {
  _enforceRateCap,
  _enforceApexApproval,
  _storePlan,
  _consumePlan,
  _idempotencyState,
  _reapExpiredIdempotency,
  _wrapSecretReturn,
  _reapExpiredSecretHandles,
} from "./policy-gates.js";

// Re-export the names that other modules import from `./policy.js` but that
// this module does not itself use. `export … from` keeps them as pure
// re-exports (javascript:S7763) without an intermediate local binding.
export { parsePolicy, loadPolicy, profileFromEnv } from "./policy-config.js";
export { _resetGateCachesForTests } from "./policy-gate-state.js";
export {
  validateApexCoverage,
  consumeApexToken,
  resolveSecretHandle,
} from "./policy-gates.js";

// PolicyError and Policy are re-exported AND used within this module (thrown /
// `instanceof`), so they remain imported above and exported as local bindings.
export { PolicyError, Policy };

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

  // Phase 6 (#1202) optional inspection hook for surface tests. Codex
  // review #1202 cycle 3 finding 2: surface-suite assertions on
  // descriptor metadata (the `klass`, `untrusted_source`,
  // `sensitive_args`, `is_write` fields that decide which wrapper
  // gates compose around the handler) can't be made from
  // `server.tool(name, description, schema, handler)` alone — that
  // signature carries only the wrapped artifacts. Production callers
  // (`mcp/ops/index.js::main()` and its `McpServer` ctx) do not set
  // this callback, so the live server is unchanged. Tests set it on
  // the FakeServer ctx to capture descriptor metadata post-validation
  // / pre-gate-composition, without copying capability maps or
  // re-parsing index.js. Written as optional-chained invocation so
  // the SonarCloud cognitive-complexity gate stays under threshold
  // (S3776: optional chaining is a single expression, not a branch).
  ctx.onRegisterDescriptor?.(descriptor);

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
