# ADR-039: Provider-neutral range substrate

## Status

Accepted.

## Date

2026-07-12

## Context

Shifter currently has provider seams for cloud utilities, backend-bundle metadata,
task dispatch, and provider-specific range mutation. Those are different concerns.
The range path still selects between AWS Terraform, GCP Compute Engine, and GDC
implementations inside provisioner modules, while pause/resume contains AWS-specific
plans and a deliberately disabled GCP path. Adding another provider to those switches
would duplicate lifecycle, validation, error, state, and security behavior.

This decision defines the one provider-neutral *range substrate* port used below the
existing CMS -> Engine -> provisioner workflow. It builds on the provider-coupling
source map in
[`branch-routing-provider-coupling-inventory.md`](branch-routing-provider-coupling-inventory.md)
and on ADR-011's root-selected backend bundles.

## Decision

Each backend bundle selects a provider family. When that provider has more than one
registered range backend, the range's persisted backend binding selects exactly one
range-substrate adapter; mutable deployment defaults never reinterpret an existing
range. The substrate is a request-scoped convergence boundary for the complete range
resource set: networks, instances, an optional NGFW attachment, and the remote-access
bindings required to reach those instances. It exposes four operations:

| Operation | Input obligation | Successful postcondition |
| --- | --- | --- |
| `provision` | Operation context plus existing, already-validated realization intent and its digest | All required owned resources exist, isolation policy is applied, required assets are ready, and non-secret resource/access bindings are returned. |
| `destroy` | Operation context plus persisted resource ownership/state | All per-range owned resources and per-range credentials are absent. Missing resources are a successful no-op; shared resources are never deleted. |
| `pause` | Operation context plus persisted resource ownership/state | Pausable compute is stopped, remote access is unavailable, and networks/state needed for lossless resume remain. Shared NGFWs remain active when another range needs them. |
| `resume` | Operation context plus persisted resource ownership/state | Paused compute is running and healthy, required NGFW reachability is restored, and remote access is ready. Resume is not reprovision. |

The port is synchronous from the provisioner's point of view: an operation returns only
after the postcondition is observed, or raises a classified failure. ECS tasks,
Kubernetes Jobs, local subprocesses, and their task identifiers are delivery mechanics
outside this port. Their successful submission is not substrate success.

### Contract shape

All four operations receive one closed, versioned operation context containing:

- selected backend identity, derived from validated root configuration rather than
  supplied by a request body;
- `request_id` as the range correlation and ownership key;
- operation name and an immutable operation/idempotency key;
- desired-intent digest for `provision` and the expected persisted-state version for
  every destructive or power operation;
- a bounded deadline/cancellation signal; and
- existing trace context, without credentials or raw user input.

`provision` consumes the existing validated realization artifact. The legacy path keeps
using `RequestSpec` / `RangeSpec` and their persisted envelope; the RAES-native path
keeps using the validated serialized `ProvisioningPlan` and the process-local
realization projection allowed by ADR-032. The substrate contract must not create a
third scenario, topology, node, network, or account schema.

Owning the lifecycle and cleanup of instance resources does not make the substrate the
semantic owner of scenario composition. The scenario realization path owns VM count and
roles, containers or nested Kubernetes, internal topology, images, services, ports,
DNS, startup order, and bootstrap behavior. The substrate may enforce provider safety,
membership, ownership, and access-binding invariants on the resulting resources, but it
must not classify scenario internals into a universal placement taxonomy. The GCP
specialization is fixed by
[`scenario-gcp-range-cell-contract-preflight-1344.md`](scenario-gcp-range-cell-contract-preflight-1344.md).

A successful operation returns one closed, versioned result containing the request and
operation identifiers, `changed` or `already-converged`, achieved lifecycle state,
canonical resource bindings keyed by authored resource UUID, and bounded warning codes.
Provider identifiers required for later cleanup live in adapter-owned state behind a
versioned state reference/projection; raw SDK/Terraform responses do not become portal
DTOs, event payloads, or public API responses.

Remote-access output is limited to readiness and non-secret binding metadata: instance
UUID, protocol, address/port, username when non-secret, and a secret *reference* when a
credential is required. Passwords, private keys, Guacamole tokens/URLs, kubeconfigs,
and provider access tokens never cross this interface. Guacamole session construction
and just-in-time secret resolution remain in the existing Engine/Mission Control access
services. A scenario declares a logical member target and access channel; the platform
resolves the concrete provider address and rejects foreign or non-member targets rather
than accepting an arbitrary scenario-supplied hostname.

### Idempotency and concurrency

- The idempotency identity is scoped to installation, `request_id`, operation, and
  desired generation. It is generated by trusted orchestration, not accepted from an
  untrusted API caller.
- Replaying `provision` with the same key and intent digest converges and returns the
  same logical bindings. Reusing the key with different intent is a conflict before
  mutation.
- Replaying `destroy` succeeds when resources are already absent. Replaying `pause` or
  `resume` succeeds when the requested state is already observed.
- Only one mutating operation may own a range generation at a time. A conflicting
  in-flight operation returns a classified conflict; adapters must not race Terraform
  locks, Kubernetes patches, or provider APIs independently.
- A timeout or interrupted provider call has an unknown outcome. Retry first observes
  provider state and resumes convergence; it must not blindly create a second resource.
- Partial provision failures retain enough ownership evidence for retry/cleanup and do
  not report `READY`. Partial destroy failures remain retryable and do not discard state
  for resources that may still exist.

Pause/resume must be lossless for every resource kind the adapter admits. Deleting and
recreating a pod or VM is not pause unless the adapter proves state and identity
preservation required by the published contract. An unsupported resource mix fails
before mutation with `unsupported-capability`; it is never silently skipped or treated
as success.

State preservation is relative to the admitted contract, not a promise that
stop/start preserves volatile execution. GCE stop/start retains persistent
resources but not RAM/application state as suspension does. A request requiring
those stronger semantics remains unsupported unless its adapter proves them;
it must not be silently narrowed. The
[participant-control profile](raes-participant-control-realization-envelope-1967.md)
therefore distinguishes native resource pause/resume from portable participant
memory, process/session continuity and a frozen world clock.

### Error contract

Adapters map provider failures into one small substrate failure record; they do not
export SDK exceptions or create provider-specific exception trees. Every failure has a
stable code, retry disposition, operation/request context, and a bounded sanitized
diagnostic. The required codes are:

| Code | Retry disposition | Meaning |
| --- | --- | --- |
| `invalid-intent` | permanent | Existing schema/realization validation or adapter preflight rejected the input before mutation. |
| `unsupported-capability` | permanent | The adapter cannot honor an admitted resource or lifecycle semantic. |
| `not-found` | permanent except destroy | The range/state required by pause or resume is absent; destroy converts absence to success. |
| `conflict` | after state refresh | Operation/generation mismatch, concurrent mutation, or state-lock conflict. |
| `identity-or-policy` | after operator correction | Workload identity, IAM/RBAC, ownership, network, or admission policy denied the operation. |
| `prerequisite` | after operator correction | Required config, tool, image, state backend, secret reference, or endpoint is unavailable. |
| `rate-limited` | retry with backoff | Provider throttling with bounded backoff/jitter. |
| `transient-provider` | retry with backoff | Retryable provider/control-plane failure. |
| `timeout-unknown` | reconcile, then retry | Completion is unknown; observe before another mutation. |
| `partial-failure` | reconcile/cleanup | Some resources changed and the target postcondition was not reached. |
| `adapter-defect` | no automatic retry by default | Unclassified invariant violation or implementation defect. |

The provisioner may translate this record into its existing failed status and bounded
operator diagnostics. HTTP and websocket layers continue using the existing authored
error envelope and must not surface the diagnostic or provider payload.

## Boundary ownership and incumbent reuse

The interface centralizes provider variation only. Existing layers keep their current
responsibilities:

| Concern | Canonical incumbent | Binding rule |
| --- | --- | --- |
| Authentication, authorization, ownership, rate limits, audit | Mission Control permissions/serializers, CTF gates, `cms.services`, `shared.AuditLog` | Substrate adapters are never HTTP entrypoints or authorization oracles. They receive an already-authorized range identity. |
| Authoring and realization intent | `shared.schemas.RequestSpec` / `RangeSpec`; ADR-031/032 RAES `ProvisioningPlan` transport | Do not duplicate or providerize scenario/topology schemas. Validate before cloud mutation. |
| Public lifecycle state | `shared.enums.ResourceStatus`, Engine/CMS state machines | Do not add provider status enums to public APIs. Adapter phases are private operation evidence. |
| Backend selection/config | `shifter/installation` loader, schema, contract, registry, runtime inventory, backend settings models | The registry advertises the substrate capability and conformance evidence. No independent `CLOUD_PROVIDER` default or branch/provider switch may select it. |
| Task delivery | `shared.cloud.TaskRunner`, `engine.ecs`, provisioner CLI command family, GCP Job admission policy | Preserve structured argv and the `range <operation> --request-id <uuid>` family. Task dispatch is not substrate implementation. |
| Persistence and reconciliation | Engine-owned range/request/instance state, existing state writers, Terraform state, range-event outbox/reconciler | Persist canonical bindings plus versioned adapter state once. Do not add per-adapter repositories or expand direct Django-table SQL; #478 owns that process boundary. |
| Network allocation and policy | existing subnet allocation/inventory, ADR-017/020/021/026/030, range-isolation model | Adapters realize the selected posture; they do not reinterpret missing controls as permissive defaults. |
| Secrets and remote access | provider secret stores, `shared.cloud`/provisioner secret adapters, Engine terminal resolvers, Mission Control Guacamole builders | Store and return references only; resolve values at the existing access boundary. |
| Events and projections | ADR-025 outbox, `range.status.updated`, reconciliation handlers | Events remain notification-shaped and provider-neutral. No resource inventory or secret data in events. |
| Errors/logging | `shared.cloud.exceptions`, `shared.errors`/API errors, `shared.log_sanitize`, provisioner `log_redact`, ECS JSON logging | One substrate classification maps into these surfaces; raw provider errors and sensitive identifiers stay internal and sanitized. |

ADR-011 continues to own public installation/backend-bundle selection. This ADR
specializes its range-runtime seam and supersedes any reading of ADR-005-R1 or
ADR-011-R4 that would model a whole range as a composition of public low-level cloud
factories. A backend bundle is metadata and selection; a substrate adapter is the
runtime implementation behind the bundle's declared range-substrate capability.

RAES backend-manifest conformance and range-substrate conformance are also distinct.
The former proves authored semantic realizability; the latter proves operational
lifecycle behavior and security invariants on a provider. Passing one does not imply
the other.

## Security requirements

Every adapter must satisfy these interface requirements rather than inherit provider
assumptions by name:

- **Identity and authorization:** use the provisioner's workload identity and
  least-privilege provider permissions. No end-user cloud credential enters the
  adapter. Mutations are limited to resources owned by the selected installation and
  `request_id`; names alone are insufficient ownership proof.
- **State:** state is encrypted, access-controlled, locked/serialized, and keyed by
  installation plus request identity. Destroy must distinguish per-range from shared
  state and must retain recovery evidence until absence is observed.
- **Network isolation:** the adapter must realize the selected ingress, cross-range,
  management, metadata/API, DNS, and egress posture and fail closed if a required
  control cannot be installed. Conformance does not override ADR-030's approved
  live-fire backend policy.
- **Secrets:** generated guest credentials and provider credentials stay in the
  provider secret store or ephemeral Kubernetes Secret. Only references may enter
  persisted state. Secret values, Terraform variable JSON, kubeconfigs, provider
  responses, and Guacamole material are prohibited from results, events, diagnostics,
  metrics, and logs.
- **Process/OS exposure:** operation and request UUID may appear in structured argv;
  credentials, config blobs, resource inventories, and secret references must not.
  External commands use argv arrays without a shell, bounded temporary workspaces,
  restrictive permissions, cleanup, and the existing admission/runtime security
  profiles.
- **Error and log leakage:** adapter diagnostics are single-line, bounded, sanitized,
  and safe for operator logs. Request/range correlation uses existing structured fields
  or fingerprint helpers; raw exception strings do not cross API/event boundaries.

### User-held client VPN specialization

A user-held OpenVPN profile is a specialization of the existing
remote-access resource, not a fifth lifecycle operation or scenario service. For a
product profile that requires it, the selected live-fire adapter must provide a
request-owned logical gateway inside the range containment boundary, one
generation-scoped owner identity/profile reference, and a server-enforced path
only to the authoritative Kali/attacker member target. The gateway may be a dedicated
resource or share another request-owned edge resource; it must not be shared across
ranges and must not run on the user-controlled target.

Product identity and authorization stay above the substrate. A trusted product
launch path explicitly mints the closed capability from server-owned ownership,
target, and lifecycle facts; topology, role, operating system, and the presence of
an access declaration do not activate VPN infrastructure. CTF derives the
credential deadline from event cleanup. Mission Control uses the CMS-owned range
lease: 30 days initially, fixed 30-day extensions, and an immutable 365-day
generation ceiling. The current lease deadline drives canonical automatic
teardown, while the immutable ceiling bounds the generation credential. Another
product must likewise supply a deadline that actually drives teardown or use an
explicitly versioned renewal/revocation lifecycle. A caller timestamp, a
caller-selected increment, a certificate beyond the generation ceiling, and an
unbounded certificate are all invalid.

The profile is created during `provision`, so `READY` includes gateway, credential,
and target-policy readiness. Infrastructure creation returns pending metadata; the
provisioner publishes the binding only after a bounded gateway service-and-policy
probe succeeds. A download resolves the existing secret at the Engine access boundary
after product/CMS ownership and state checks; it does not mint a new certificate per click.
Pause makes the tunnel unavailable and resume restores the same generation. Destroy
deletes the gateway, immutable issuer, and client/server material. Because a downloaded
credential cannot be recalled, an in-place ownership transfer or spare adoption is
refused while a VPN binding exists. Spare selection applies that compatibility check
before old-range teardown, and the write boundary rechecks it. Recovery for a new owner
must destroy the old generation and provision a new one before `READY`. The
provisioner-only issuer remains immutable until teardown so a completed-generation
retry reuses the exact runtime material. Certificate expiry is bounded by the
trusted product deadline; stale or greater-than-397-day capability
windows fail before provider mutation rather than being shortened underneath an
active range. Expiry does not replace lifecycle deletion. GCE uses a distinct
no-role gateway service account per range generation and grants it read access
only to that generation's server-identity secret.

The common network contract permits only the resolved target, normally with a
server-enforced `/32`, and denies client-to-client, other-range/member, platform,
management, metadata/API, and default-route access. Client profile content is not an
authorization oracle. Client profiles/private keys and CA signing material do not
enter portal/application state, adapter/Terraform state, public results, events,
task payloads, environment, argv, logs, metrics, or errors; the substrate returns
one provider secret reference. Every live-fire adapter eligible for an enabled
product profile must pass the same real-client handshake, target reachability,
negative isolation, lifecycle, secret-deletion, and capacity tests before the
capability is advertised.

The full HTTP, identity, secret-delivery, profile-shape, parity, and extensibility
guardrails are recorded in
[`ctf-openvpn-participant-access-preflight-1695.md`](ctf-openvpn-participant-access-preflight-1695.md)
and
[`non-ctf-openvpn-range-access-preflight-1696.md`](non-ctf-openvpn-range-access-preflight-1696.md).

## Conformance obligations

An adapter is trusted by executable evidence, not by registry declaration or review.
The canonical, provider-neutral conformance suite is black-box against the published
port and runs unchanged for every adapter. It must verify:

1. closed/versioned inputs and outputs, unknown-field/version rejection, and no
   mutation on invalid intent or unsupported capability;
2. provision of networks, instances, optional NGFW, and access bindings, with stable
   authored-UUID correlation and no secret values;
3. repeated provision, destroy, pause, and resume; same-key/different-intent conflict;
   serialized concurrent operations; timeout observation before retry;
4. partial-create cleanup, partial-destroy recovery, provider-side missing resources,
   drift, and preservation of recovery state;
5. lossless pause/resume, remote-access unavailability while paused, readiness after
   resume, and correct shared-NGFW no-op behavior;
6. ownership isolation: one range cannot mutate another range or shared installation
   resources, and destroy removes every owned resource without orphans;
7. stable error-code/retry mapping, bounded redacted diagnostics, structured
   observability, and provider-neutral status/events; and
8. adapter-declared security probes for identity scope, state protection/locking,
   network/metadata isolation, secret-reference-only outputs, and remote-access
   containment.

The deterministic suite runs in CI with a controllable provider harness. Promotion to
`stable` additionally requires the same lifecycle/security scenarios against a
disposable real-provider environment, with retained non-secret evidence. Adding a
capability or resource kind adds a shared fixture and obligations; it is not an
adapter-local test that other adapters may omit. Backend maturity must reflect this
evidence. An adapter missing any mandatory operation may remain experimental but cannot
claim full range-substrate conformance or be selected for a profile that requires it.

## Initial adapters and extensibility seam

- `aws` selects the AWS Terraform range-substrate adapter. Terraform state/locking and
  the existing AWS range isolation/IAM/secret controls remain adapter obligations.
- `gcp` has distinct GCE and GDC range-substrate adapters selected by the persisted
  `Range.range_backend` binding through `shared.range_instantiation_policy`.
  GCE is the default and approved live-fire backend; ADR-030 limits GDC to explicitly
  permitted non-user modes. Pause/resume is implemented for both GCP adapters (issue
  #614): GCE stop/start over the Compute Engine instances client and GDC VM Runtime
  stop/start over the existing `kubectl virt` primitive shipped in the provisioner
  image, each observing the resulting instance state. Lifecycle capability is decided
  by the realized asset mix through `shared.range_lifecycle_capability` and enforced at
  two tiers: the CMS gate and the Mission Control projection refuse/omit an unsupported
  range pre-dispatch, and the provisioner re-checks before any mutation. A GDC scenario
  Pod has no persistent state, so any range containing a pod-backed asset remains
  unsupported (fail-closed with `unsupported-capability`); pod delete/recreate is never
  presented as pause. Evidence for one GCP adapter or resource mix must not advertise
  lifecycle capability for the other. The remaining conformance gaps are the generic
  black-box substrate suite (see below) and disposable real-provider promotion evidence;
  a range whose complete realized mix is not proven lossless remains unsupported.
- Azure is deferred. It may enter only as another backend bundle and adapter behind the
  published contract after its adapter passes conformance. Azure must not add
  provider branches to CMS, Engine, CTF, Mission Control, shared schemas, or public
  status/error contracts.

The extensibility parameter is the persisted, registry-selected substrate adapter plus
its declared resource/lifecycle capability profile. The next provider or a future GCP
substrate is a registry entry, adapter, backend settings model, and conformance evidence.
It does not require re-editing the four-operation port or domain workflow.

### Optional warm-pool activation capability

Issue #28 adds an optional `range-warm-activation/v1` capability beside the
four-operation substrate; it does not add a mandatory fifth operation to
`range-substrate/v1`. An adapter advertises this capability only for the exact backend
and realized resource mix for which it can satisfy both of these semantics:

- existing `provision` accepts a trusted `warm-prepared` allocation profile and
  converges the normal immutable realization intent into a system-owned, quarantined
  generation. Infrastructure and scenario bootstrap may be ready, but no participant
  credential, participant access binding, session, or publicly reachable participant
  path exists;
- `activate` consumes an atomically claimed generation, its unchanged realization and
  compatibility digests, the expected adapter-state generation, and a trusted
  owner/workspace/product projection. It removes or rotates every pre-claim guest,
  provider, and access identity, creates fresh claimant-specific bindings, and reports
  success only after isolation and access readiness are observed. The claimant identity
  is loaded from the immutable Engine operation input, never from HTTP, environment, or
  process arguments.

The allocation claim is an Engine/CMS persistence operation above the adapter. It must
commit before asynchronous activation and must not hold a database lock across provider
I/O. A miss, race, disabled policy, or `unsupported-capability` result takes the existing
cold `provision` path with the already-validated launch inputs. Once claimed, a failed
generation is never returned to the ready pool; it is quarantined and destroyed through
the canonical lifecycle. `destroy`, not an adapter-local pool cleanup API, remains the
only resource-removal operation.

Warm eligibility is digest-based. It includes the persisted backend/partition and
placement class, instantiation purpose and product/access posture, the exact validated
RAES package/plan plus resolved image and artifact bindings, and every other immutable
input that changes realized resources or isolation. Mutable scenario identifiers,
aliases, current registry contents, and caller-supplied compatibility keys are
insufficient. The legacy `RequestSpec`/`RangeSpec` embeds `user_id`; therefore it cannot
be warm-reassigned without a separate versioned ownership-neutral intent contract and
must remain unsupported/cold-fallback rather than mutating or contradicting persisted
intent.

The detailed cross-layer guardrails are recorded in
[`range-warm-pool-preflight-28.md`](range-warm-pool-preflight-28.md).

## Program-reference traceability

The issue #1322 body names references that do not all resolve to substrate work in the
canonical repository history available to this checkout. They are recorded explicitly
so ambiguous numbers do not become invented requirements:

| Reference | Repository evidence | Interface disposition |
| --- | --- | --- |
| #283 | Merged `dev` PR in canonical history; no range-substrate contract | Out of scope. |
| #478 | Documented in the REV1 review as the provisioner/Django persistence-boundary remediation | Cross-cuts all four operations but is not a substrate operation. The port must not expand the raw-SQL coupling it is intended to replace. |
| #265 | Merged “Remove OWUI and MCP” PR in canonical history | Out of scope. |
| #277 | Canonical history associates the number with terminal-UI cleanup merged through PR #284 | Out of scope. |

Every remaining Backend Bundles & Substrate program item must declare one or more of
`provision`, `destroy`, `pause`, `resume`, or `out-of-scope`, plus the affected resource
families (`network`, `instance`, `ngfw`, `remote-access`) and required conformance
fixtures. A stale or cross-repository issue number must be corrected before it is used
as an implementation contract.

## Whole-repository scope

The implementation is constrained across these existing surfaces:

- backend contract and selection: `shifter/installation/{schema,loader,contract,registry,runtime_inventory}.py`;
- API/auth/workflow: Mission Control serializers/permissions/views, CTF gates/bridges,
  CMS range services, and audit logging;
- shared contracts: `shared.schemas`, `shared.enums`, `shared.cloud`, shared error/API
  envelopes, message envelopes, and import-linter boundaries;
- Engine orchestration/state: `engine.services`, `engine.ecs`, Engine models, task
  identifiers, range status handlers, outbox, and reconciliation;
- provisioner execution: CLI parser, config/env validators, range operation/runners,
  state writers, event producer, logging/redaction, Terraform base, AWS Terraform
  modules, and GDC network/VM/pod/NGFW modules;
- access/secret handling: Engine terminal/secret resolvers, provider secret adapters,
  Mission Control Guacamole bootstrap/payload builders, and per-instance secret
  references;
- platform policy: ADR guard/import rules, gitleaks, Terraform/Checkov/TFLint,
  Kubernetes admission/PSS/network policy, actionlint, kube-linter, and kubeconform.

## Non-goals and prohibited designs

- No implementation is part of this ADR, and it is not an implementation plan.
- No new public scenario DSL, duplicate `RangeSpec`/RAES model, duplicate
  `ResourceStatus`, per-provider API DTO, repository, validator, event family, or
  exception hierarchy.
- No redesign of CMS/CTF admission, public lifecycle endpoints, task runner, durable
  outbox, Guacamole authentication, or the installation root schema.
- Cancellation remains workflow policy: it may converge through `destroy`, but it is
  not a fifth substrate operation.
- Image baking, content ingestion, platform install/upgrade, and control-plane teardown
  are outside the range-substrate port.
- Do not expose low-level create-network/create-VM methods as the public backend
  contract; adapters may use such helpers privately.
- Do not treat task submission, a Terraform exit code without readiness checks, a
  swallowed 404, or an emitted status event as proof that the target postcondition was
  reached.
- Do not make provider selection from a branch, environment default, resource-state
  sniffing, or `if provider` switches outside the backend registry/adapter factory.
- Do not persist or return raw provider payloads, derive cleanup solely from naming,
  delete shared NGFW/network resources from a range operation, or discard state after
  partial failure.
- Do not emulate unsupported pause by destroy/recreate, silently skip non-pausable
  assets, or mark a nonconformant adapter stable.
