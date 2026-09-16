// Side-effect gate enforcement for the shifter-ops policy layer:
// apex-coverage validation, per-class rate caps, the two-phase plan
// store, apex out-of-band operator approval, idempotency, and secret
// handles. Split out of policy.js (javascript:S104); behavior is
// unchanged.

import { randomBytes, randomUUID } from "node:crypto";

import { PolicyError } from "./policy-config.js";
import {
  IDEMPOTENCY_TTL_MS,
  SECRET_HANDLE_TTL_MS,
  PLAN_TTL_MS,
  MAX_PLAN_STORE_SIZE,
  APEX_APPROVAL_TTL_MS,
  APEX_TOKEN_BYTES,
  MAX_PENDING_APEX,
  planStore,
  rateCapWindows,
  pendingApex,
  registeredDescriptorNames,
  idempotencyCache,
  secretHandles,
} from "./policy-gate-state.js";
import { _fingerprintArgs } from "./policy-fingerprint.js";
import { _writeAudit } from "./policy-audit.js";
import { _toolPolicy } from "./policy-tool-policy.js";

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

export {
  _enforceRateCap,
  _storePlan,
  _consumePlan,
  _enforceApexApproval,
  _idempotencyState,
  _reapExpiredIdempotency,
  _wrapSecretReturn,
  _reapExpiredSecretHandles,
};
