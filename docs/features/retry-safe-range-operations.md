# Retry-safe range operations

Public API clients can launch a range idempotently by supplying a caller retry
key, so a lost launch response can be recovered without creating a duplicate
range. Cleanup outcomes are reported truthfully: a dispatched teardown is not
reported as verified until the resources are actually gone.

## Idempotency-Key header

Send an `Idempotency-Key` header with `POST /api/v1/mission-control/range/launch/`:

- **First use** dispatches the launch and binds the key to the resulting
  operation. The response includes `"recovered": false`.
- **Replay with the same key and the same launch selections** (scenario, agents,
  workspace) recovers the original range instead of launching again. The response
  includes `"recovered": true`.
- **Replay with the same key but different selections** returns **409 Conflict**;
  a key is bound to exactly one launch intent.

The key is caller-supplied and scoped to the acting user in one deployment: two
different users may use the same key value without collision, and a key never
lets one actor recover another actor's operation.

### Caller-key rules

- Maximum length **200 characters**; a longer key returns 400.
- Leading and trailing whitespace is trimmed; an empty or whitespace-only key is
  treated as **absent** (the launch behaves as an ordinary, non-idempotent
  launch).
- A key is retained for a bounded retry window after the operation is created so a
  delayed retry still recovers it. Reusing a key after that window is a new
  binding; do not reuse a key for an unrelated launch.

## Truthful cleanup outcomes

Teardown status distinguishes what is *dispatched* from what is *verified*:

- Requesting a destroy or cancel dispatches an asynchronous teardown; the range
  moves to a `destroying` state and its status endpoints report that truthfully.
- Capacity and assignment are released only when the range actually reaches a
  terminal `destroyed` state, not when the teardown is merely dispatched.
- An operation whose cleanup evidence is unavailable or incomplete is reported as
  **pending/unknown**, never as an empty success. A timeout, a dead-letter, a
  failed status, or a missing worker task is not treated as proof that resources
  are gone.

Status, results, and cancellation continue to use the existing range read and
lifecycle endpoints, authorized by range ownership on every call.
