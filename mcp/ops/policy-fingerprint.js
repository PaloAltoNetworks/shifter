// Idempotency fingerprinting helpers for the shifter-ops policy layer:
// stable canonical JSON, the wrapper-control key list, and the
// arg-fingerprint / control-strip functions. Split out of policy.js
// (javascript:S104); behavior is unchanged.

import { createHash } from "node:crypto";

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

export { _fingerprintArgs, _stripWrapperControlArgs };
