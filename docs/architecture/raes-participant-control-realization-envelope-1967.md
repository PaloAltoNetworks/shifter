# RAES Participant-Control Realization Envelope

Status: accepted architecture guidance; implementation not present

Date: 2026-09-06

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1967>

Portable authority: OpenRAE ADR-108 and
`participant-control-composition/rev1` (PC-01 through PC-15), accepted at
OpenRAE/rae revision
`ebb70a34b8e7d1cc8964c443841ae57e12ed1014`.

ADR: ADR-058. Shifter requirement: [GEN-2005](../requirements/GEN-2005/requirement.md).

Delivery and proof belong to #1968 and #1969. This decision selects a design;
it does not implement a control mechanism, widen a backend manifest, add a
schema, or assert released support. Native surface assessment includes Shifter
revision `9516f802385af56cfe9ea1b3b906aa0eb7dc0d8e`.

## Decision

Shifter selects one closed local profile for initial implementation:

| Identity field | Selected value |
| --- | --- |
| Local profile | `shifter-ctf-gce-range-lifecycle` |
| Profile version | `1` |
| Operating mode | CTF cyber-range, one event participant's current dedicated RAES range generation |
| Mechanism composition | RAES capability restriction + approval/audit protocol + resource control |
| Approval provider | Explicit proposal-bound approval in the CTF product control decision by an actor whose current event authority is verified |
| Authorization provider | `ctf.services.authorization` with exact `EventCapability.RANGES`; CMS/Engine retain target, ownership, workspace, lifecycle, and generation authorization |
| Evidence sink | Request-attributed strict `shared.audit`; evidence is not approval or workflow state |
| Effect provider | ADR-039 `range-substrate/v1`, adapter `gcp-gce` |
| Native action set | whole-range `pause` and `resume`, with the persistent-resource limits below |
| Selected portable governed effects | permit, deny, withhold, audit, and request review around an admitted proposal; these names retain PC-09 meanings |
| Operation transport | `shifter.provisioner-operation` version `1`, generation-fenced by `operation_id` |
| Portable interpreter/conformance boundary | `shared.raes`, using the exact released RAES contract and verdict implementation |

The mechanism-family labels above name the accepted RAES architectural
families; they are not new Shifter wire literals. `shared.raes` must consume the
actual identifiers, DTOs, versions, and verdicts from a released RAES artifact.
The Shifter-local profile tuple is application policy and must never be emitted
as a replacement portable participant-control schema. Its exact identity and
canonical digest, and the exact released mechanism, provider implementation,
and provider-configuration identities and digests, are admission bindings. They
cannot be filled with architectural family labels or the existing
provisioning-only `SHIFTER_REALIZER_CONFIGURATION` digest.

This composition fits Shifter because it already has an exact event-scoped
`CTFParticipant` to dedicated `RangeInstance` association, central organizer
authorization, a default-deny persistent-resource lifecycle capability check, a
persisted GCE range-backend binding, a durable generation-fenced operation path,
provider readback, and strict Engine result auditing. It does not depend on
mechanism parity with LilRAE.

An authored scenario may express portable RAES control semantics. It may not
name Python code, a service, a task command, a cloud adapter, a Shifter profile,
or a provider implementation. Shifter selects the exact local profile and
provider from closed server policy plus the persisted range binding. An unknown
mechanism/profile/version/effect/provider combination is unsupported and fails
before control-workflow persistence, launch, or provider mutation. A bounded
denial audit may still be emitted; it is not evidence that a control occurred.

Native pause/resume are not new portable effect tags, nor synonyms for
interrupt or shutdown. An API-409 proposal/control reference must bind through
the released closed API-424 mapping to an already admitted native range
action. A permit only admits that parent; it does not execute it. Request
review creates an independently admitted supervisory obligation, not an
automatic approval. #1072 must supply the applicable closed bindings and
valid/invalid fixtures; if it cannot represent this exact mapping, the profile
is unsupported. A free-form reference, callback or parameter bag cannot fill
the gap.

### Research basis and alternatives

The [issue research record](https://github.com/Brad-Edwards/shifter/issues/1967#issuecomment-5555762123)
contains the source inventory, methods, limitations and SDL lineage assessment;
the [accepted-authority update](https://github.com/Brad-Edwards/shifter/issues/1967#issuecomment-5556555834)
supersedes its earlier status of #1068. These sources informed the selection:

- The RAES SDL lineage ledger distinguishes Open Cyber Range authoring/model
  ancestry from CyRIS provisioning, CybORG actor/action models, and
  CACAO/STIX/OCSF workflow, reference and telemetry influences. None is a
  compatibility promise. See the pinned
  [lineage ledger](https://github.com/OpenRAE/rae/blob/fb4cb4b7002305e7062bc51f1eda77c5852b2642/contracts/provenance/sdl-lineage-ledger-v1.json).
  Shifter's
  ADR-024 hard cutover remains binding; retired CyberScript is not an extension
  seam. The [RAES design-intent clarification](https://github.com/OpenRAE/rae/blob/fb4cb4b7002305e7062bc51f1eda77c5852b2642/docs/research/language-extensibility/design-intent.md)
  keeps author constraints separate from backend
  realization choices: a witness must satisfy the requested constraints, not
  silently substitute a weaker profile or force operator configuration into SDL.
  The associated ADR-105 is proposed, not authority to invent released SDL syntax.
- [Saltzer and Schroeder](https://www.cl.cam.ac.uk/teaching/1011/R01/75-protection.pdf)
  motivate complete mediation and least authority.
  [Schneider](https://www.cs.cornell.edu/fbs/publications/EnfSecPols.pdf)
  supports conjunction of applicable restrictions, not arbitrary effect
  composition. RAES PC-05–PC-10 supplies the latter's actual contract.
- [CaMeL](https://arxiv.org/html/2503.18813v2) and
  [Fides](https://arxiv.org/html/2505.23643v1) depend on mediated data/control
  flows and available provenance. Shifter's interactive access and guest
  execution do not establish that coverage. Dynamic IFC is therefore not
  selected; missing influence information is not an empty known label.
- Formal [shield synthesis](https://arxiv.org/abs/1501.02573v2) needs an
  observable property and enforceable intervention boundary.
  [ShieldAgent](https://proceedings.mlr.press/v267/chen25ae.html) supplies
  bounded empirical results, not that formal guarantee. Neither justifies an
  arbitrary in-guest runtime-shield claim here.
- Current work such as [AgentSpec (ICSE 2026)](https://ink.library.smu.edu.sg/sis_research/10278/)
  and [capability-oriented agent security (CAIS 2026)](https://www.yichenxu.me/files/publications/securing-agents/paper.pdf)
  reinforces explicit, limited enforcement boundaries; it does not establish
  Python/GCE realization or require a new Shifter policy language.
  [Prudentia (2026 preprint)](https://arxiv.org/html/2602.11416v1) makes approval
  cost and human supervision relevant limitations, not proof of reliable
  operator decisions.

The initial use is a deliberate session/resource intervention, such as
reviewing a teaching-session pause, not an automated attack detector. Capability
restriction, explicit review and bounded resource actions fit existing service
ownership and measurable GCE postconditions. Handoff, IFC and shielding lack
the selected identity/propagation/actuation coverage; they are not approximated
by an approval row, firewall, message or resource power operation. No mechanism
is selected merely because another backend uses it.

### Resource and memory limits

The native GCE adapter maps pause to stop and resume to start. Google's
[stop/start contract](https://docs.cloud.google.com/compute/docs/instances/stop-start-instance#stop_an_instance)
does not preserve RAM/application state as suspension does. This profile claims
only observed compute power state and the admitted persistent resources and
identity; it does not freeze a human participant, world clock, process,
network session or application. It does not reset portable participant memory
or erase history/influence. A request requiring stronger memory semantics is
unsupported, not silently narrowed.

Admission requires a nonempty, dedicated GCE member set whose complete mutable
footprint is within the bound participant resource scope. Version 1 excludes
Local SSD-dependent preservation, unobserved resources, automatic external
restart controllers, shared participant resources and any attached NGFW that
could enter the native lifecycle cascade. The existing helper's asset-kind
check is necessary but cannot establish these additional conditions. Keep
ADR-039 access unavailability/readiness checks; never disable platform
isolation or expand the admitted footprint to make pause/resume succeed.

## Declared World And Operating Envelope

The declared world is the participant, accounts, nodes, networks, and other
world resources present in the validated and compiled RAES scenario, narrowed
to the one current Shifter range generation that genuinely realizes them. For
the initial profile, the controllable unit is the complete dedicated range, not
an inferred individual RAES agent or an arbitrary VM selected by a caller.

The following are out of world and remain backend/platform security concerns:

- the Django control plane, PostgreSQL, workers, provisioner workload, and
  provider control APIs;
- organizations, workspaces, event authority, API tokens, sessions, and service
  identities;
- Shifter management cloud projects/accounts, IAM, KMS, secret and metadata services,
  management networks, range-isolation firewalls, and tenant boundaries;
- operation inputs/results, launch intents, audit rows, event outboxes,
  credentials, terminal/Guacamole brokers, and deployment configuration.

An attack on or protection of those surfaces is not a RAES world action,
observation, intervention, or participant-control effect. A control operation
must never weaken them or report their state as participant evidence.

This is an ownership boundary, not a ban on modeling a technology. Isolated
scenario accounts, test credentials or modeled directory/metadata services can
be in world when explicitly declared, admitted and realized there; they never
inherit management authority. ADR-056 containment and ADR-057's limited
control-plane transport claims remain independent prerequisites, not in-world
mechanism results.

| Environment class | Initial disposition |
| --- | --- |
| GCP/GCE CTF cyber-range | Supported only by the exact profile above after #1968 implementation and #1969 real-boundary proof. |
| Mission Control/non-CTF range | Unsupported: range ownership is not a trusted mapping to an individual RAES participant. |
| GDC non-user demo/BAS | Unsupported: it has no admitted participant workload and no selected control profile. |
| Simulated environment | Unsupported: Shifter has no simulation participant-control provider or readback boundary. |
| AWS range | Unsupported for this profile: no released and proven RAES participant-control realization is selected. |
| Federated environment | Unsupported: no controller handoff, remote trust, lease, revocation, or evidence protocol is selected. |
| Genuinely live/external environment | Unsupported: Shifter does not claim authority over external production actors or systems. |

These are limits of the selected Shifter profile, not a claim that RAES cannot
describe simulated, federated or genuinely live worlds. Such a world needs its
own admitted authority, provider, crossing coverage and evidence.

## Existing Surface Inventory

| RAES/control concern | Current canonical surface | Boundary for #1968 |
| --- | --- | --- |
| Portable RAES semantics | `shared.raes`; ADR-031 import confinement; exact `raes==2.0.0` and `raes-env-packs==3.1.0` pins | Only this package may parse the future released control contract. The current pins contain no Shifter-usable participant-control release, so they authorize no claim. |
| Backend capability | `shared/raes/backend-manifest.json`, `shared.raes.manifest` | Currently `provisioning-only`; `participant_runtime`, `observation`, `orchestrator`, and `evaluator` are null. Existing sidecars do not widen it. |
| Participant semantics | compiled RAES participant behaviors and ADR-032-R10 `ParticipantAccessBinding` | Access is not control, and participant-invariant access is not participant identity. The initial control target comes from the event participant's current dedicated range binding. |
| Run/context identity | `shared.raes.runs.validate_run_binding` and bounded `RunDescriptor`; compiled plan persisted in Engine `Range.range_config` | Reuse released RAES validation and the one-way run-binding identity, but do not overclaim the incumbent: the descriptor is not currently persisted through range launch and establishes neither an active participant-control episode/controller nor a history cut. Those exact released-runtime identities must bind to the admitted compiled package/run and current range generation before control admission. |
| Product participant | `ctf.models.CTFParticipant`, event-scoped CTF services | A CTF participant, Django user, RAES participant, range owner, and runtime node remain different identities. |
| Action/effect execution | `cms.services` lifecycle facade, `engine.services._lifecycle`, ADR-039 range substrate | Reuse pause/resume only. Direct organizer range actions remain Shifter product actions unless they are bound to a validated portable control occurrence. |
| Intervention | ADR-051 `CommunicationIntent` RAES provenance and CTF communication policy | Disclosure, external direction, and intervention remain distinct. A communication is not a control effect; an intervention needs the exact selected mapping and observed effect. |
| Observation/readback | `OperationResultInbox`, Engine result applier, `Range`/`Instance` state, `RangeEventOutbox` | Provider completion is true only after the current generation's closed result is validated and its complete target state is observed. Queue/task acceptance is not effect success. |
| RAES operation evidence | `RaesOperationRecord`, `shared.raes.operations`, `shared.raes.projections` | Reuse receipt/status/reference projections where the released contract permits; never add control semantics to JSON opportunistically. |
| Participant history/evidence | `RaesParticipantRuntimeRecord` and reference-only projection helpers | These local sidecars are not a portable participant-control DTO or workflow store. Do not add control requests, approval state, provider payloads, or verdicts to them. |
| Durable command | `ProvisionerLaunchIntent`, immutable `OperationInput`, canonical command validator | Reuse one generation-fenced launch path. Do not add a control queue or pass RAES payloads in task arguments. |
| Durable result | append-only `OperationResultInbox`, Engine-only applier | Reuse digest conflict, version, ownership, ordering, stale-generation, and result-shape checks. |
| Audit | `shared.audit`; strict Engine result audit | Approval/intent audit must become strict and durable before effect. `AuditLog` remains evidence, never queue or approval workflow state. |
| Notifications | ADR-025 `RangeEventOutbox` plus authoritative reconciliation | Status events are propagation signals, not portable observations or the control result store. |
| Errors/logging | `CMSError`, CTF domain exceptions, `shared.exceptions.ValidationError`, `shared.api.errors`, `shared.log_sanitize`, provisioner `log_redact` | Map at existing boundaries with stable reason codes; do not create a participant-control exception hierarchy or expose raw RAES/provider failures. |
| Verification | `tests/shared/raes` conformance/fixture style; CTF organizer authorization/audit tests; CMS lifecycle tests; Engine launch/applier/generation tests; provisioner pause/resume tests | Extend the existing vertical seams and negative matrices. #1969 adds disposable real-GCE effect/readback/isolation proof; mocks alone cannot release the claim. |

## Placement, Trust, Lifecycle, And Persistence

`shared.raes` owns portable parsing, exact profile compatibility, bounded
projection, released composition/conformance calls, and access to the released
authoritative runtime. It performs no product authorization or effect. That
runtime, not a Shifter sidecar or product model, commits portable control
history, provider-state transitions, finite causal budgets, effect claims, and
control dispositions. CTF owns event-participant resolution, the explicit proposal-bound
product approval, live `EventCapability.RANGES` authorization, and the local
occurrence-to-effect mapping. It reaches CMS only through `ctf.bridges`; CTF
never imports CMS or Engine models. CMS owns the public participant/range
control facade and revalidates the current target, workspace, lifecycle, and
capability. Engine owns operation generation, durable launch, input/result
persistence, domain state, result application, and status events. The
provisioner and ADR-039 `gcp-gce` adapter alone touch the actual GCE guests.

Select the durable single-owner embedding posture P1 from
[RAES ADR-104](https://github.com/OpenRAE/rae/blob/ebb70a34b8e7d1cc8964c443841ae57e12ed1014/docs/decisions/adrs/adr-104-runtime-control-plane-architecture.md):
one immutable target/run binding per authoritative store and owner. CMS owns
installation, lifecycle and routing to that owner through the existing
`shared.raes` embedding boundary. Store lifetime and owner recovery are outside
the pausable range; pausing a guest must not remove control history. No second
portable runtime, shared multi-tenant store or concurrent worker ownership is
inferred. P0's ephemeral state is insufficient; P2's HTTP front end is not
required, and P3 distributed coordination is not claimed. A deployment unable
to provide the released durable-store/ownership contract cannot admit this
profile. This decision adds no listener or fictional provisioner Job service.

### Exact bindings and composition

The following are fixed local provider-instance names for the design, not
new portable mechanism literals or assertions that provider code is installed:

| Mandatory role | Local instance/version | Input and result boundary |
| --- | --- | --- |
| Capability restriction | `shifter-ctf-range-capability/1` | Immutable native authority, admitted action/resource scope and current capability snapshot; a deterministic constraint, not guest-wide command filtering |
| Explicit review | `shifter-ctf-explicit-review/1` | Exact proposal-bound approval/denial/expiry and authority references; a mandatory constraint plus separately admitted review request |
| Resource control | `shifter-range-resource-budget/1` | Declared native action footprint and released durable causal-budget/provider-state snapshot; bounded resource admission, not a spending or CPU/memory guarantee |

Each admitted instance pins its actual portable mechanism/protocol revision,
profile revision/content digest, installed implementation artifact/version/digest,
configuration digest, authority and state scope, inputs, evidence and limitations.
Do not substitute the profile name, source branch, provisioning configuration
digest or artifact hash for trust or capability validation.

Resolution uses PC-03 context K: run, apparatus binding, participant, episode,
subject, crossing, direction, final sink/audience/destination, controller,
authority, policy revisions, state cut, expected history heads, provider-state
references, trigger root, predecessors, memory scope and governed time/order.
The CTF participant and range association are necessary but insufficient:
the trusted compiled participant/controller/run binding must be persisted and
validated, including exclusive resource scope. Never infer it from a team,
role, host name, AD domain controller, event organizer or access credential.

Provider resolution is pure over immutable snapshots. It cannot invoke GCE,
deliver to a participant, mutate authoritative state or call a model covertly.
Next provider-state references are proposals for the same RAES commit, discarded
on conflict. Only RAES performs composition: a finite admitted acyclic dependency
graph, correctly typed result slots, and conjunction of all incumbent gates and
mandatory resolved permits at the same K. Fact, constraint, advice and effect
request slots are distinct; no advice score can supply authority.

Mandatory deny blocks the parent; withhold keeps it undispatched with explicit
resumption/expiry conditions. Abstain, missing, unknown, unsupported, failed or
weakened mandatory support cannot release it. Stale results and history
conflicts require bounded re-resolution at a fresh K, never reuse of an old
permit. Keep all contributing/blocking reasons in canonical order. This profile
has no advisory provider; adding one cannot secretly make advice a required
guarantee or alter these fail behaviors.

Same-slot identical requests deduplicate; different canonical content conflicts.
Pause and resume targeting the same state conflict unless an explicit order and
revalidation of the preceding observed postcondition permits a new action.
There is no lexical winner or implicit restart. Every required predecessor must
be realized and revalidated before the parent. Independent member calls may be
parallel only for the profile's declared disjoint resource footprint; parallelism
does not imply an atomic world transition.

PC-12 causal limits cover root lifetime, depth, effect count, rule firings,
resolution attempts and fan-out, with finite installation-admitted values in the
bound configuration. Counts, provider-state transitions, claims and history commit
together in the RAES store. Re-resolution, child review/audit effects, restart,
replay or controller transitions cannot mint a new root or replenish a budget.
Terminal evidence is bounded and must not recursively trigger unlimited effects.
Product rate limits, Redis windows, range quotas, retry counts and timeouts are
additional controls, not the portable causal budget.

The control decision must retain immutable references/digests for the portable
occurrence and context/history cut, the exact local profile/provider/configuration,
approval actor and authority source, event participant, range request, explicit
effect dependencies, exact operation generation, and terminal outcome. When
control originates in an ADR-051 intervention, its portable provenance remains
in the immutable communication aggregate. The minimum persistence seam is a
narrow CTF-owned product control decision keyed to those references; it owns
only Shifter authorization, approval, fence, and correlation lifecycle. It does
not own or copy portable control history, provider-state transitions, causal
budget balances, effect claims or composition decisions. Those remain in the
released RAES authoritative runtime, while provider execution truth remains
in Engine. Conformance verdicts come from the released checker and are
referenced as version-pinned evidence, never locally reimplemented.
The decision must not be hidden in
`CommunicationIntent` JSON, `AuditLog` JSON, `Range.range_config`,
`CTFScheduledTask.metadata`, a participant-runtime sidecar payload, frontend
state, or task memory.

The current CTF range-lifecycle API authorizes with `EventCapability.RANGES`,
then its service calls CMS with `participant.user`. That target-owner
substitution may be reused to reach the owned range, but it is neither explicit
approval nor approver identity and must not attribute the control to the
participant. The control boundary must carry the effective event-authority
actor/source and the target owner as separate facts, preserve the existing
self-service CMS authorization path, and strict-audit the actual approval
decision before the launch intent can be claimed. Authorization, approval,
execution admission, and audit evidence remain distinct records and outcomes.
`admin_external_audit` supplies the correct intent-before-effect shape only for
platform-admin overrides; its owner/staff no-op behavior is not the approval
provider required by this profile. Every admitted authority source needs the
same strict decision evidence, while the existing platform-admin override audit
remains intact.

Approval is a deliberate durable decision on the exact proposal digest, action,
target scope, policy/configuration revision and finite validity interval.
Denial and expiry remain explicit. The same currently qualified organizer may
request and explicitly confirm a proposal; version 1 does not claim two-person
approval or resistance to approver error. A changed proposal, target, authority
or configuration requires new approval. Recording approval does not execute,
endorse data or enlarge authority; dispatch requires fresh resolution and all
native gates. A scenario, service principal or participant cannot self-approve
through content. Approval request visibility is separately sink-admitted.

The current CTF/CMS/Engine lifecycle facade returns a product response or
boolean/task acceptance rather than the newly reserved `operation_id`, and its
already-paused/already-ready path may create no operation at all. Claimable
control evidence must instead bind the decision to the exact Engine generation
that actually executed, or explicitly record an occurrence-specific no-op
against authoritative current state. It must never recover correlation by
querying the latest range operation, treating the cached CTF status as
readback, or treating a task identifier as an operation generation. Pause and
resume continue to use the canonical `resource=range` operation transport; a
second RAES-specific pause/resume command or payload is not introduced.

Authorization is not an indefinitely reusable snapshot. Native approval and its
strict audit precede the RAES expected-head commit of control state/budget/intent.
The product decision and exact Engine operation reservation/binding then commit
before the launch intent is claimable. These are separate durable boundaries:
there is no two-phase commit or atomicity claim across the RAES store, Django
database and GCE. Recovery reconciles exact references across crash gaps.

The PC-11 logical effect key is the admitted run/root/rule-revision/effect-slot/
firing-epoch identity, not a state cut, retry number, HTTP request or task id.
It maps to one native Engine operation; same key with different content is a
conflict. Persist the relationship between the approved source generation and
the operation's legitimately advanced generation. Never use a latest-operation
query, reject the action's own reserved generation as stale, or create a new
operation because a response was lost. Resource incarnation, Engine operation
generation and RAES episode are distinct: a legitimate pause reservation does
not replace the world, whereas replacing the resource incarnation invalidates
its old admitted binding.

Event cancellation, participant removal, range replacement and authority
revocation suppress the exact pending operation through public services in the
same native transaction as invalidation. Extend Engine's existing locked
pre-Job gate; its destroy-specific provision-interrupt flow is not a generic
suppression primitive. Crucially, Job creation is not the final GCE invocation:
the admitted generation/authority/worker-ownership fence must also hold at each
actual cloud call. Neither task acceptance nor result-applier fencing proves it.
The provisioner consumes a closed native dispatch grant through the existing
operation boundary; it must not query CTF models or interpret portable approval.

Conflicting mutations/revocation cannot acknowledge a completed fence while an
older worker can still invoke. An expired worker lease or uncertain provider
call does not authorize blind takeover: prevent further effects until old
ownership and actual provider state are authoritatively reconciled. If the
adapter cannot enforce that boundary, the requested guarantee is unsupported.
After invocation begins, revocation is not rollback. Partial/failed/indeterminate
outcomes remain explicit, without a claim of instantaneous cancellation.

All native entry points affecting an actively controlled binding must enforce
these gates or refuse the operation; legacy endpoints cannot bypass the
profile. Unbound product lifecycle behavior remains separate. An emergency
out-of-world management action that breaks the admitted binding invalidates
the realization; it is not silently represented as a governed in-world effect.

Pause/resume is convergent but not atomic across a multi-VM world. Unsupported
asset mixes must be rejected before mutation by
`shared.range_lifecycle_capability`. Once provider I/O begins, a timeout or
member failure may leave a partial state. That outcome is `partial-failure` or
`timeout-unknown`, never success; it remains operator-visible and must be
observed/reconciled before retry. A later retry reuses the operation's
idempotency/generation rules rather than issuing blind compensating calls. The
current range worker collapses member failures to `cloud_operation_failed`;
that existing behavior is insufficient for the selected claim until #1968
preserves the ADR-039 partial/indeterminate distinction end to end. Its current
pause path also treats an NGFW-pause failure as non-fatal; that cannot satisfy a
whole-range postcondition that requires the participant access path to be
unavailable. The provider must either prove the exact selected postcondition or
reject that target/guarantee before mutation.

## Claim And Evidence Contract

| Proposed claim | Real implementation boundary | Authoritative readback | Failure behavior | Released RAES conformance | Explicit limitation |
| --- | --- | --- | --- | --- | --- |
| The local profile is supported | `shared.raes` exact released contract adapter plus server-owned profile policy | published exact profile/mechanism/provider/configuration identities, versions, and canonical digests plus deployed provider identity | unknown version, profile, mechanism, provider, configuration, effect, or digest rejects before persistence/mutation | released profile/PC-01–PC-15 fixtures and verdict API; no local verdict clone | no implication for any other Shifter, RAES, or LilRAE profile |
| The target has admitted participant resource scope | CTF event/participant service -> `ctf.bridges` -> CMS current range resolver and `shared.raes` binding | event, product participant, compiled RAES participant/controller/run/episode, package, resource scope, request/range and generation join | missing, non-dedicated, ambiguous, foreign, replaced or stale join rejects opaquely | portable identity/target fixtures plus Shifter authorization tests | no inferred agent selection, shared-resource control or union of participant policies |
| Capability restrictions constrain the parent | Pure capability result at K plus incumbent CMS/Engine gates | exact allowed action/resource binding and decision reference; denial proves no prohibited invocation | any unsatisfied mandatory slot blocks the parent | PC-01–PC-06 fixtures and native boundary-negative tests | not command filtering or confinement inside a guest |
| Review was requested and decided | Released request-review binding -> CTF product supervision -> explicit authorized decision | matching request/proposal/approval-or-denial/expiry references and strict audit | unsupported binding, failed sink or absent/expired approval cannot dispatch the parent | API-409/API-424 review fixtures and real service/UI evidence | review, approval and execution are separate; no two-person or infallible-human claim |
| Resource causality is bounded | Released RAES runtime/provider-state commit | root, counters, limits, effect slots and committed history heads across recovery | exhaustion, conflicting heads or unavailable durable store block new effects | PC-10–PC-12 fixtures and restart/replay/exhaustion cases | not an expenditure, CPU or RAM quota |
| The effect was approved | explicit proposal-bound CTF product approval; separate current `EventCapability.RANGES` authorization; strict all-source `shared.audit` evidence | immutable approval/effect correlation, authority source, exact operation binding, and request-attributed audit | absent/mismatched approval, revoked/insufficient actor, invalidated event/participant, audit failure, or stale/replaced target prevents actual invocation | approval/audit protocol fixtures plus revocation, lifecycle-invalidation, pre-dispatch-race, and audit-failure tests | no autonomous scenario/range/controller approval; no approval inferred from authorization, content, or audit |
| Native pause was effected | CMS lifecycle -> Engine generation -> final invocation fence -> ADR-039 `gcp-gce` stop/readback | every admitted GCE member observed stopped, required access unavailable and Engine current generation applied `PAUSED` | unsupported rejects before mutation; partial/timeout stays failed or indeterminate and visible | #1968 contract tests; #1969 disposable real GCE proof | admitted persistent resources only; no RAM, frozen-world, destroy or quarantine claim; non-atomic across members |
| Resume was effected | same path using ADR-039 `gcp-gce` start/readback | every admitted member observed running/ready and Engine current generation applied `READY` | same fail-closed admission and truthful partial/timeout handling | #1968 contract tests; #1969 disposable real GCE proof | readiness is range lifecycle readiness, not arbitrary in-guest application health |
| Evidence is durable and auditable | released RAES authoritative runtime plus product decision refs, launch intent, immutable input, append-only result inbox, Engine applier, strict audit, and ADR-025 outbox | bounded audience-authorized projection joining RAES claim/history refs, product approval/authorization, operation disposition, current state, and audit correlation | dependency loss never invents approval or success; pending/failed/indeterminate remain distinct; retry preserves logical effect identity | released evidence/runtime contract plus replay, ordering, budget, redaction, sink-policy, and outage cases | no shadow runtime; no raw commands, rejected content, provider payloads, backend-private state, credentials, terminal streams, or general RAES observation claim |

No capability may be advertised merely because code, a row, a manifest key, or
a documentary mapping exists. #1969 real-provider evidence is required before a
released Shifter artifact claims the profile. A CTF communication being
delivered, a task being queued, a cloud API accepting a call, or one VM reaching
the target state proves less than the selected effect.

#1968 may exercise an installed candidate through an explicitly admitted
proof configuration without advertising released support. #1969 must bind
the actual implementation/configuration and installed RAES artifacts to the
observed results before capability publication. API-407 declarations, runtime
results, native readback, audit and released conformance must agree at that
same evidence scope; a provisioning-only sidecar cannot widen a manifest.

### Required cases for the selected claims

The terms in this table describe outcomes, not new Shifter wire enums.

| Case | Required observation |
| --- | --- |
| Deliberate teaching/session intervention | A review trigger creates an admitted supervisory obligation; explicit approval then permits the bound native pause/resume, with real GCE and access readback. Displaying a message or approving alone is insufficient. |
| Known in-world adversarial influence under permitted ordinary policy | The admitted test content can remain in the world while the resource-control decision follows its own constraints. This profile claims no IFC propagation, endorsement or adversarial detection. A requested SEM-233 enforcement profile remains independent and unsupported without its required instrumentation. |
| Denial, missing/failed mandatory result, or expired approval | Zero prohibited parent delivery/invocation; only independently authorized bounded rejection/review/audit evidence. |
| Changed proposal, profile/configuration digest, participant or generation | Old approval/permit cannot authorize the replacement; reject or resolve a fresh K with new approval where required. |
| Concurrent pause/resume or conflicting same-key content | No lexical winner, hidden restart or duplicate dispatch; explicit conflict or admitted ordered postcondition and revalidation. |
| Budget exhaustion, resolution loop or excessive member fan-out | Durable root limits block further effects; restart, replay, handoff or episode reset cannot replenish them. |
| Crash before RAES intent commit | No native dispatch; absent intent is not reconstructed as a completed effect. |
| Crash after intent commit, before/after native reservation or invocation | Reconcile the exact logical key and generation. Known absent execution can resume under fresh gates; uncertain execution requires readback and cannot be repeated blindly. |
| Revocation after Job creation but before a cloud call | Final invocation fencing prevents stale execution; launch/result fencing alone must fail this test. An uncertain old worker blocks takeover. |
| Partial member failure, cloud timeout or stale result | No whole-range success; retain observed per-member state, exact operation disposition and recoverable indeterminate evidence. |
| Foreign tenant/range/participant, unsupported asset or NGFW cascade | Opaque refusal with zero out-of-scope resource mutation; same-cell positive controls distinguish enforcement from general outage. |
| Audit, durable-store, provider or operation-integrity failure | No invented approval or success. Report failed/invalid realization and bounded native integrity evidence, not an in-world attack event. |
| Already stopped/running | Current authoritative readback plus occurrence-specific approval/correlation, without a fabricated provider execution. |
| Decision/reason/receipt at an unauthorized sink | No raw or hidden information escapes; failure, absence and timing follow admitted sink policy, independently of the parent. |

## Cross-Cutting Layers And Canonical Incumbents

| Layer | Required gate/reuse |
| --- | --- |
| HTTP authentication | Reuse bearer-first `ApiTokenAuthentication` and session authentication. A malformed bearer token fails closed and never falls through to a session; session mutations retain CSRF. |
| Token scope | Reuse the exact existing `ctf:event:write` scope for the organizer range-management audience. Do not add a broad `raes:*` or wildcard scope. A future external controller is a new audience and is unsupported here. |
| CTF authorization | Reuse `resolve_event_authority` with the exact `EventCapability.RANGES`, including event-owner, delegated-staff, and platform-admin source rules. Recheck it at the CTF service/claim boundary; the existing API-view check alone is not durable authorization. Workspace membership, scenario authorship, range ownership, UI visibility, an approval row, or audit evidence is not event authority. |
| Approval and invocation freshness | Wire invalidation into event cancellation, participant removal, range replacement and authority changes through existing public services. Commit native decision/operation correlation before claimability; extend the locked launcher gate and enforce the admitted generation/authority/ownership fence at each actual cloud call as specified above. Communication hooks and destroy-specific provision interruption do not establish this control fence; no direct provisioner access to CTF models. |
| Target authorization | Re-resolve the event-qualified participant and current dedicated range; then reuse CMS ownership/workspace/lifecycle gates without confusing target owner with approving actor. Bind the released controller/episode/run/world identities to the admitted package, `RunDescriptor` identity where parameterized, compiled plan, and current range generation. Return the same opaque not-found/denial behavior for foreign targets. |
| RAES validation/runtime | Only `shared.raes` loads the released portable DTO, validates exact profile/mechanism/provider/configuration identities, versions, digests, package/occurrence/context/history-cut binding, invokes released composition/conformance, and commits through the released authoritative runtime. All mechanisms see the same cut; mandatory missing/stale/unknown/unsupported/failed/weakened/abstaining/conflicting results deny. No raw SDL reparse, app-local portable serializer, local composer/verdict, or sidecar runtime. |
| API/request shape | Use explicit DRF serializers and a closed request shape. The caller identifies the already-bound intervention/participant occurrence; server code derives target, provider, operation, and profile. DRF does not reject unknown members by default, so reuse the explicit `initial_data` unknown-field check used by `workspaces.api.serializers`. Duplicate JSON-member detection is a parser-level concern and is not supplied by a serializer; do not claim that guarantee without a shared parser boundary. |
| Capability/provider admission | Join the CTF participant/event to the current CMS `RangeInstance`; require its server-derived CTF source/workspace/scenario and validated RAES package source/digest; then reuse persisted Engine `Range.range_backend` and instantiation purpose, `shared.range_lifecycle_capability`, current `ResourceStatus`, and current operation generation. Never re-read an environment selector or infer RAES/control support from a scenario-id string, cloud/provider name, or range ownership alone. |
| Persistence/wire shape | Keep only product authorization/approval/fence/correlation references in the narrow CTF-owned control decision. The released RAES runtime owns control history, provider-state transitions, finite causal budgets, effect claims, and control dispositions; conformance evidence references the released checker. Reuse `ProvisionerLaunchIntent`, immutable `OperationInput`, `shared.operation_envelope`, `shared.operation_results`, and append-only `OperationResultInbox` for execution. Preserve logical effect identity across retry/replay and exact keys, bounds, digests, ordering, ownership, and generation fencing; do not add control JSON to generic operation input. |
| Provider/config | Reuse ADR-039 `gcp-gce`, `load_gce_range_cell_config`, GCE power helpers, persisted backend/purpose, least-privilege workload identity, private range networking, current timeouts, and the exact deployed image/source identity. Bind the released participant-control provider/configuration identity and canonical digest separately; `SHIFTER_REALIZER_CONFIGURATION` is provisioning evidence and cannot be reused under a new meaning. The initial profile adds no scenario or handler-local environment setting. |
| Secret handling | Control records carry identifiers/digests only. Existing session/token secrets stay in their authentication stores; provider credentials stay in workload identity/secret stores. Nothing new enters database JSON, audit detail, events, metrics labels, docs fixtures, task payloads, environment dumps, or provider state. |
| OS/process exposure | Preserve canonical structured argv: resource/operation plus request and operation UUIDs only, using canonical `resource=range`; the provisioner CLI has no `raes-range pause/resume` implementation. Preserve the GCP validating-admission policy's fail-closed launcher/service-account/image/argument/env/volume/hardening checks, dedicated launcher RBAC and network policy, no service-account-token mount, non-root/read-only/drop-all/seccomp Job, and per-Job Secret delivery. Portable control payloads, actor data, profile documents, cloud identifiers, credentials, commands, scripts, and configuration blobs do not enter argv, shell strings, process titles, or workflow output. |
| Result validation | Reuse Engine's digest/version/ownership/current-generation/step-order/result-shape applier and ADR-039 postcondition checks. A result does not mutate domain state until every gate passes. |
| Audit/observability and sinks | Strict-audit the approval decision before effect and reuse strict Engine outcome audit. Apply the released audience/sink policy independently to decisions, reasons, approvals, receipts, and evidence; portable presence is not permission to log, emit, audit, or publish. Preserve bounded digest-bound references and limitations. Log only stable codes, operation/profile names, counts, timings, and sanitized/fingerprinted ids through `shared.log_sanitize`/`log_redact`; never raw rejected content, payloads, provider-private state, or exception text. |
| Error envelopes | Portable failures become bounded RAES diagnostics inside `shared.raes`; service failures use existing CTF/`CMSError`/shared validation classes; `/api/v1` uses `shared.api.errors`. Raw RAES, database, provider, IAM, network, and guest errors do not reach users. |
| Events/read models | Reuse ADR-025 outbox and reconciliation for product status projection. WebSocket/notification delivery is advisory and never control readback or success evidence. |
| Cross-layer imports | Preserve ADR-001, `.importlinter`, and `scripts/check_layer_imports/layer_imports.yaml`: CTF -> `ctf.bridges` -> public `cms.services` -> public `engine.services`; only `shared.raes` imports `raes_*`. |

Implementation must admit finite budget/approval limits, exact provider
configuration and durable-owner/storage policy before enabling this profile.
These are installation-owned, not scenario-owned choices. Any new typed setting
and closed validator must pass through `config/settings.py`,
`config/env-manifest.json`, `installation/schema.py`, `installation/registry.py`,
the runtime inventories, provider renderers, deployment overlays, and parity
tests. This design adds no executable configuration. A handler-local `os.environ` read, free-form JSON profile,
scenario-selected module, or provider-specific UI branch is forbidden.

## Extensibility Seams

The required seam is a closed server-owned profile table keyed by the exact
portable profile/mechanism/effect/provider/configuration identities, versions,
and canonical digests plus verified operating mode and persisted range
provenance/purpose/backend adapter. Those verified bindings and the exact
context/history-cut reference are the stable resolution parameters; the
selected local profile name/version/digest is an output, never caller input. A
profile maps to a fixed composition of approval provider, authorization
provider, effect dependencies and set, effect provider, readback policy,
audience/sink policy, and evidence policy. It is data/policy over existing
service seams, not a plugin loader and not caller-selected code.

The next provider variation is another ADR-039 adapter realizing the same
persistent-resource pause/resume postconditions. It can join only with its own exact
profile/provider identity and real conformance evidence; adding it does not edit
CTF workflows or weaken GCE evidence. The initial profile already requires a
server-derived RAES participant selection persisted with ownership context.
Until then, Mission Control/multi-participant cases fail rather than unioning
policies. Dynamic IFC, runtime shielding, capability restriction inside guests,
controller handoff, and live-environment control each require a distinct
mechanism profile, trust model, provider, failure contract, readback, and
conformance evidence; none extends this profile by adding an enum member.

## Gotchas And Anti-Patterns

- A participant-control controller is not an AD domain controller, organizer,
  Django actor or access account. Engine lifecycle terminology and a
  non-persisted `RunDescriptor` do not supply an active RAES episode/history cut.
- Do not put portable DTOs, workflow history, provider state or budgets in
  `RaesParticipantRuntimeRecord`, `RaesOperationRecord`,
  `CommunicationIntent` JSON, `range_config`, task metadata or audit JSON.
- Do not add a shadow runtime, executor, queue, event bus, outbox, audit table,
  evidence repository, provider plugin registry, config parser, error envelope
  or exception hierarchy. The narrow CTF product record does not duplicate
  RAES or Engine authority.
- Keep explicit unknown-field rejection and parser-level duplicate-member
  validation distinct. A default DRF serializer supplies neither guarantee.
- Keep native `resource=range` pause/resume dispatch, exact operation
  correlation, all-source audit and existing authentication/CSRF/scope rules.
  Task identifiers, cached status and a latest-operation lookup are not proof.
- Do not reuse CTF's immediate asynchronous restart sequence, Engine's
  destroy-specific provision interruption, or the non-fatal NGFW cascade as
  the selected control/fencing/postcondition contract.
- Do not infer a current provider observation from an idempotent no-op.
  Correlate the occurrence and read back current state without inventing a call.
- Audit, evidence, approval and receipt visibility are independently admitted
  sinks. Their existence, reason and timing are not automatically public.
- Do not turn platform compromise/protection into an in-world occurrence or
  promote provisioning evidence into a control, IFC, shielding or parity claim.

## Non-Goals And Implementation Gates

- No mechanism implementation, API, model, migration, worker, provider call,
  manifest change, package upgrade, or conformance assertion in #1967.
- No generic plugin manager, second RAES runtime, Shifter-authored portable
  participant-control schema, simulation backend, external controller, or
  controller-handoff protocol.
- No individual in-guest process/action control, dynamic IFC, runtime shielding,
  network reconfiguration, destroy/rebuild, resource resize, command execution,
  or arbitrary intervention.
- No expansion to AWS, GDC, non-CTF/Mission Control, federated, or genuinely live
  environments, and no change to product naming.
- No replacement of CTF authority, CMS/Engine range lifecycle, ADR-039,
  ADR-043, shared audit, provider secret stores, ADR-025 events, terminal access,
  or Guacamole.

The current repository pins RAES 2.0.0 and environment packs 3.1.0; the accepted
OpenRAE design revision is not by itself a released consumable control contract.
#1968 is blocked until the required RAES artifacts are released and pinned at
exact versions, with the import boundary and conformance tests updated together.
A git revision, copied DTO, local verdict, UID list, or `DRAFT` upstream
requirement is not a substitute.

GEN-2005 is the cross-cutting Ground Control constraint for this decision and is
currently `DRAFT`. Its documentation links to #1967, #1968, #1969, ADR-058, and
this envelope do not claim an implemented runtime or conformance.

The accepted upstream #1068 design is sufficient for #1967. #1968 additionally
requires the released artifacts from OpenRAE/rae
[#1070](https://github.com/OpenRAE/rae/issues/1070) (semantics),
[#1072](https://github.com/OpenRAE/rae/issues/1072) (contracts),
[#1069](https://github.com/OpenRAE/rae/issues/1069) (runtime), and
[#1071](https://github.com/OpenRAE/rae/issues/1071) (conformance), in that
dependency order. These are native GitHub blockers, not merely prose links.
Pin the consumable release versions and their exact contract/fixture identities
before mechanism implementation; accepted design commits alone do not suffice.

GEN-2005 is reviewed and activated with implementation, with IMPLEMENTS/TESTS
links to the actual delivered artifacts. #1967 retains DOCUMENTS links and
makes no such runtime claim. Support advertisement additionally requires #1969
real-boundary proof. Neither LilRAE implementation nor its evaluation issues
are a prerequisite or evidence of Shifter support.

Core profile implementation/proof does not depend on CTF communications
#2050/#2054: those integrations depend on this core, and reversing the order
would create a cycle. ADR-051 provenance remains relevant when a communication
later invokes an already admitted typed control mapping; communication delivery
is not the control mechanism or its proof.

## Validation

This architecture-only change must pass:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Existing ADR registry, guardrail-documentation and import checks protect
repository structure; they do not enforce or prove the proposed runtime
guarantees. This documentation-only delivery uses the user-approved design
review and existing document checks, without a new executable policy contract.
Implementation remains subject to the stack-native checks and behavioral tests
in `AGENTS.md`; #1969 supplies the disposable real-provider
control/readback/isolation evidence. Mandatory audit is distinct from optional
experimental capture, retention or export.
