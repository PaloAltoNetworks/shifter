// Module-level gate state for the shifter-ops policy layer: the
// idempotency / secret-handle / plan / rate-cap / apex caches and the
// registered-descriptor set. Split out of policy.js (javascript:S104).
//
// ES modules are singletons, so every gate module importing these
// containers shares the same instances — the wrapper and the
// test-reset helper operate on identical state, exactly as before the
// split.

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

export {
  IDEMPOTENCY_TTL_MS,
  SECRET_HANDLE_TTL_MS,
  PLAN_TTL_MS,
  MAX_PLAN_STORE_SIZE,
  planStore,
  rateCapWindows,
  APEX_APPROVAL_TTL_MS,
  APEX_TOKEN_BYTES,
  MAX_PENDING_APEX,
  pendingApex,
  registeredDescriptorNames,
  idempotencyCache,
  idempotencyInFlight,
  secretHandles,
};
