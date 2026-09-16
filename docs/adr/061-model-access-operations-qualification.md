# ADR-061: Model access is released through revocation and operating evidence

## Status

Proposed for [#681](https://github.com/Brad-Edwards/shifter/issues/681),
PLAT-202, 2026-09-06. Depends on ADR-059 and ADR-060.

## Context

A working model response does not prove safe teardown, bounded cost,
availability during an event, or recovery without resurrecting credentials.
Google explicitly distinguishes deleting a service-account key from revoking
tokens already minted from it. Direct-access migration must account for that
residual authority, including shared-principal blast radius.

## Decision

Treat allocation, participant capability, provider credential, request lease,
and range lifecycle as separate state with explicit owners and correlations.
Engine invalidation stops new admissions transactionally. Brokers check
continuation leases at least every five seconds, use a two-second control
timeout, and stop downstream delivery and upstream transport within ten
seconds of committed revocation or loss of authorization service. These are
qualification targets, not measured guarantees. Provider-side execution may
continue; retain its maximum charge and report uncertainty.

Pause, reset, destroy, quarantine, ownership/participant revocation, expiry,
and policy withdrawal all invalidate model access before reporting access
withdrawal complete. Resume requires current admission and a fresh grant
epoch, even if the underlying range generation did not change. Cleanup uses
persisted original provider/secret references and cannot delete a successor.

Ship through disabled, synthetic validation, isolated canary, bounded cohort,
legacy drain, and qualified operation. Rollback drains or disables model
access; it never restores guest provider credentials. A database restore
starts model admission disabled and must invalidate restored grant epochs,
reconcile in-flight reservations, and issue fresh participant capabilities.

Keep prompts, completions, tool arguments/results, credentials, body hashes,
and raw provider errors out of logs, audit, traces, crash dumps, and evidence
exports. Engine commits a body-free decision/accounting audit record before
dispatch; existing shared audit and protected external evidence remain the
authorities. Provider logging/retention configuration needs explicit review;
application body-free logging does not imply zero provider retention.

The [operations design](../ops/model-access.md) defines owners, failure
responses, service objectives, sizing, retention, recovery, and acceptance
evidence. GCP qualification feeds #2091. Cross-cloud qualification is tracked
separately and cannot be inferred from GCP results.

## Alternatives and consequences

Provider billing alerts and expiring guest keys are useful residual controls,
but do not replace broker revocation or admission. Disabling a shared legacy
service account may affect multiple ranges; migration inventory and an
operator-visible cohort drain are required.

The design intentionally trades availability for authorization and bounded
spend during datastore, control-service, and policy failures. Offline replay,
background retries after ambiguous dispatch, and automatic credential-path
fallback are unsupported. Separate accounting, broker availability, and
upstream availability measurements make those outcomes visible.

## Provider basis

[Google key deletion semantics](https://docs.cloud.google.com/iam/docs/keys-create-delete#delete_service_account_key)
state that minted short-lived credentials survive key deletion; revocation
can require disabling the principal. The implementation must measure the
effective window for its actual credentials and policies. No universal
provider revocation latency is asserted here.

## M06 deployment enforcement

The [GCP package](../architecture/model-access/gcp-packaging.md) supplies
disabled Helm resources and chart-derived Actions artifacts, digest-bound
release verification, drain settings and versioned TLS references. The GCP
script quality lane installs the same pinned Helm binary to test the actual
compatibility renderer. The
[operator probes](../ops/model-access-gcp-probes.md) distinguish local structural
checks from the live IAM, LB/CNI and rotation evidence required by M10.
Neither infrastructure provisioning nor a passing health probe qualifies
model admission. The ADR remains proposed pending runtime qualification.

M06 review hardening binds control rollouts to the applied runtime ConfigMap,
protects both authorization-path deployments with disruption budgets, and
limits mounted ConfigMap payloads to 96 KiB before deployment. The combined
Actions manifest excludes the broker from all incumbent platform egress
policies regardless of generated resource names; dedicated policy owns DNS.

Self-review additionally binds both deploy adapters to current root readback,
preserves the Actions Engine worker's runtime references on the control
process, restarts control after secret synchronization, and uses foreground
deletion to complete pod drain before withdrawing broker policy. Direct Helm
input rejects non-private or malformed IPv4 coordinates and shared TLS names.
