// Per-tool policy resolution and the class-driven decision helpers for
// the shifter-ops policy layer: tool-policy merge, description
// redaction, env policy, two-phase detection, and MCP schema
// augmentation with wrapper-control keys. Split out of policy.js
// (javascript:S104); behavior is unchanged.

import { z } from "zod";
import { PolicyError } from "./policy-config.js";

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
  const augmented = baseSchema ? { ...baseSchema } : {};
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

export {
  _toolPolicy,
  _maybeRedactDescription,
  _enforceEnvPolicy,
  _isTwoPhaseClass,
  _augmentSchemaWithControlKeys,
};
