# Private model broker runtime (M05)

Issue [#2122](https://github.com/Brad-Edwards/shifter/issues/2122) completes the
existing standalone broker and Engine control boundary. This is a local runtime
contract, not a cloud, load, restore or full PLAT-202 qualification record.
[ADR-059](../../adr/059-range-model-access-broker.md), the
[preflight](broker-preflight-2122.md) and [security design](security.md) retain
their authority and qualification requirements.

## Ownership and closed routes

`python -m model_broker` starts without Django, database configuration or portal
secret hydration. Only Messages, count, authenticated logical models, exchange,
refresh and private health routes exist. The broker never executes a local tool
description or accepts a participant-selected upstream URL. Its provider registry
binds the exact admitted shard; Engine's existing source service uses the shared
cloud factory and reauthorizes after a secret read outside database locks.

`python -m engine.model_access_control` owns the workload-authenticated
`/control/v1/` facade. Its public `engine.services` operations authenticate,
reserve, dispatch, continue and finish existing requests. A separate provisioner
identity with an operation-bound audience issues enrollment. Guest and portal
credentials have no control authority. Finish intentionally remains callable
after participant revocation so the original liability can still settle.

GCP assertions verify signature, issuer, audience, expiry, verified email and
the immutable numeric `sub`. Terraform reads both service-account `unique_id`
values; active installer and Helm projection require distinct broker/provisioner
IDs. Recreating an account with the same email does not preserve its authority.
AWS retains the fixed signed regional STS assertion and exact role binding.

## Enforced bounds and failure behavior

| Boundary | Implemented limit |
| --- | --- |
| HTTP headers | 32,768 aggregate bytes, 64 fields, 256-byte names, 16,384-byte values; duplicate/conflicting authentication and framing rejected. The H11 incomplete-event parser is also bounded at 32,768 bytes. |
| Participant bodies | 4,096 bytes for exchange/refresh; Messages/count at most 1,000,000 bytes, tightened by grant limits; depth 32, closed fields, exact `2023-06-01` version and no beta features. |
| Streaming | Provider events at most 1 MiB and total normalized output at most 8,000,000 bytes; complete small events are forwarded immediately without a size-coalescing buffer. Every downstream send is bounded at five seconds. |
| Deadlines and fences | Absolute request deadline from admission, at most 120 seconds and never past the grant hard expiry; continuation every two seconds with a two-second total control timeout. Cancellation closes upstream before a best-effort one-second downstream error. |
| Anonymous abuse admission | Per broker process: 120 accepted requests per socket peer and 4,096 total per 60-second window. Control exchange/enroll/refresh: 600 per socket peer and 1,200 total per process/window. Key cardinality is bounded and keys contain no token or content. |
| Credential rotation | At most 60 successful exchange/refresh rotations per credential per minute, persisted under the same row lock as one-use consumption. Re-enrollment/successor transfer does not reset this budget. |
| Synchronous control work | Eight general workers and four independent continuation/finalization/readiness workers, with no admitted queue. Cancelled callers retain their slot until underlying work ends. PostgreSQL statements are bounded at 1,500 ms and locks at 1,000 ms. |
| Broker credential work | Eight workload-identity workers, independent of eight provider-credential workers. Both retain slots across caller cancellation; stalled provider authentication cannot queue unbounded work or exhaust the workload-identity executor. |

Process-local load shedding is not financial authority or a deployment-wide rate
limit. Engine's applicable spend/rate/concurrency accounts remain authoritative.
Opaque guest tokens are hashed, exchanged once and rotated by locked compare-and-
swap. A lost response cannot replay plaintext or restore a consumed token. The
rotation budget never extends the original hard expiry. Request retry HMACs stay
in restricted accounting records; completed retries return metadata, not content.

The broker rejects malformed private replies before treating them as authority.
Unknown usage, disconnects, deadlines and provider failures retain conservative
liability. Neither HTTP redirects nor automatic post-dispatch retries or provider
fallback are enabled. No cancellation acknowledgement claims that provider-side
execution necessarily stopped.

Readiness performs an authenticated control check including database reachability;
liveness does not depend on the provider. SIGTERM starts admission/active-stream
drain before the server waits for HTTP tasks. Startup emits fixed errors, and
transport SDK loggers cannot propagate headers, signing inputs or provider
diagnostics even when process DEBUG logging is enabled. This does not authorize
external tracing or request capture.

## Verification and evidence boundaries

`tests/engine/services/test_model_broker_http.py` runs real participant, broker,
control and provider TLS sockets with real Engine persistence. Only external
provider credentials/endpoints and IAM certificate retrieval are synthetic; the
workload signature verifier remains real. Cases include JSON/SSE/count, malformed
and conflicting requests, one-use rotation, completed retry, provider errors and
redirects, slow consumers, disconnects, revoke, control loss and signal drain.
The PostgreSQL case races refresh through the HTTP stack. Adjacent credential
tests race both enrollment and refresh; control tests prove database timeout and
independent lifecycle worker capacity. Startup/log/audit/accounting sentinels and
ASGI stalled-send/deadline regressions complement the socket cases.

The socket tests require Linux and an RFC1918 interface whose peer address is
preserved. On a host that SNATs local bridge traffic, run the same checkout and
Python environment in an isolated local container network, with the PostgreSQL
test service reachable there. Do not relax production subnet verification to
accommodate host NAT. These tests prove neither a cloud load balancer's source
preservation nor effective IAM, provider invoices, supported cohort size or live
revocation. Record that evidence through the existing qualification procedures.
