// Audit + output-sanitization helpers for the shifter-ops policy
// layer: result classification, field redaction, safe-output arg
// sanitization, and the audit-record writers. Split out of policy.js
// (javascript:S104); behavior is unchanged.

import { appendAuditRecord, sanitizeArgs } from "./audit.js";

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
function _applyFieldRedaction(target, fields, placeholderFor) {
  if (!Array.isArray(fields) || !target) return;
  for (const field of fields) {
    if (target[field] !== undefined) {
      target[field] = placeholderFor(field);
    }
  }
}

function _isPlainObject(value) {
  return value && typeof value === "object" && !Array.isArray(value);
}

function _safeOutputArgs(args, descriptor, policy) {
  if (args === null || args === undefined) return args;
  const sanitized = sanitizeArgs(args, policy.auditConfig().redact ?? []);
  if (!_isPlainObject(sanitized)) return sanitized;
  _applyFieldRedaction(
    sanitized,
    descriptor?.untrusted_inputs,
    (field) => `<redacted: operative ${field}>`,
  );
  // Codex review #1201 cycle 2: `sensitive_args` is the descriptor
  // escape hatch for fields that aren't free-form operative payloads
  // (handled by untrusted_inputs) and aren't covered by audit.redact's
  // suffix classifier, but still must not appear in plan summaries
  // or audit records. The `approve` tool uses this for its `token`
  // arg — the apex design says the token MUST NEVER appear in audit.
  _applyFieldRedaction(sanitized, descriptor?.sensitive_args, () => "<redacted>");
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

// Audit helper for the planned/cached/success branches; keeps the
// wrapper bodies linear instead of repeating the audit call shape.
function _audit(policy, descriptor, args, started, outcome) {
  _writeAudit(policy, descriptor, args, started, outcome);
}

export { _writeAudit, _audit, _safeOutputArgs };
