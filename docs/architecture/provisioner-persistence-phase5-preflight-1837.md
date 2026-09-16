# Provisioner Persistence Boundary — Phase 5 Preflight (#1837)

Status: pre-implementation guidance

Date: 2026-07-26

Issue: GitHub #1837, phase 5 of #478

This note narrows ADR-043 and
`provisioner-persistence-boundary-preflight-478.md` to the ACES result family
and the remaining read-only projections. It records boundaries and cutover
guardrails; it is not an implementation plan.

## Authoritative Boundary

An ACES operation generation has one immutable input and one authoritative
result path:

- Engine materializes the serialized ACES `ProvisioningPlan`, the byte-free
  content-delivery bindings, the relevant enabled image candidates, and any
  resolved backend ownership value into `OperationInput` in the same
  transaction as the launch intent.
- The provisioner reads exactly that row by the canonical `operation_id`,
  validates it, performs cloud work, and appends closed status/evidence/snapshot
  results through `append_operation_step_result`.
- The Engine applier validates and fences the result, persists any ACES sidecar
  evidence, applies the Range lifecycle transition, writes strict lifecycle
  audit, and enqueues the normal ADR-025 notifications in its transaction.

The provisioner must not continue emitting ACES status/snapshot events or
querying `mission_control_range`, `engine_request`,
`engine_aces_content_delivery_binding`, `engine_aces_image_mapping`, or
`engine_instance` for these inputs on a cut-over generation. A rolling
compatibility consumer may remain temporarily for already-launched old tasks,
but new generations must not dual-emit to the event outbox and result inbox.

## Identity And Concept Boundaries

`request_id` and `operation_id` are intentionally different:

- `request_id` remains the stable range/request correlation used by CMS,
  Mission Control, sidecar lookup, and downstream notification groups.
- `operation_id` is the ADR-043 lifecycle generation minted by
  `engine.launch_intents`; it fences one provision, destroy, pause, or resume
  episode and is the result-replay identity.
- New ACES `operation_status` and `runtime_snapshot` records produced from the
  result inbox carry the canonical generation as their `operation_id`.
  Historical evidence rows that used `request_id` as an operation id remain
  valid history. The accept-time `operation_receipt` is outside this result
  cutover and remains request-scoped; it must not be treated as generation
  authority. Do not rewrite either, and do not generate request-id-as-operation-
  id for new provisioner results.
- The integer Engine `Range.id` is not ownership or correlation. ACES currently
  uses it in deterministic cloud-resource and secret naming, so it may cross
  the input boundary only as an opaque legacy realization key. It must never
  select an Engine row or authorize a result; `request_id` plus the locked
  generation do that.

An ACES operation status is also not a Shifter range status. Reuse
`shared.aces.status.project_operation_status` for the explicit ACES-state to
`ResourceStatus` mapping. Do not make result step names, provider task states,
sidecar states, and `Range.status` interchangeable.

## Immutable ACES Input Projection

The ACES payload is a bounded operational projection, not a joined ORM DTO.
It composes the existing contracts:

- the existing serialized plan produced by
  `shared.aces.runtime_target.serialize_provisioning_plan` and consumed by the
  fail-closed provisioner `aces_plan.parse_plan`;
- `shared.aces.content_delivery.DeliveryBinding.to_transport` /
  `DeliveryBinding.from_transport`;
- the existing enabled image-candidate shape consumed by
  `shared.aces.image_policy.resolve_from_candidates` and
  `aces_gce_image.resolve_gce_image`; and
- normalized backend/purpose values from
  `shared.range_instantiation_policy` and the write-once Range ownership
  binding.

Project only image rows relevant to source names or source-less-node OS
families in the plan, in stable natural-key order. Each entry needs only
provider, source name/version, image reference, and optional machine/disk
defaults. Do not transport registry primary keys, notes, enabled flags,
timestamps, disabled rows, or the whole tenant registry. Key the projection by
`(provider, source_name)` so a later ACES provider adds candidates without
changing the contract's top-level concepts.

Content bindings remain byte-free and reference-only: no payload bytes,
bucket, URL, signed URL, credential, guest path, or environment value.
Reconstruct and validate `DeliveryBinding` objects at the consumer boundary;
database constraints and trusted creation history are not substitutes for
wire validation.

Legacy backend evidence is evaluated on the Engine side while it still owns
the `engine_instance.state` rows. The projection carries only the normalized,
unambiguous result (`gce`, `gdc`, or the existing fail-closed absence), never
raw instance state or a generic evidence/query document. Preserve the current
rule that mixed, missing, or unknown asset types do not become a guessed
backend, and never fall back to the mutable selector for legacy GCP destroy.

The entire envelope remains under `MAX_ENVELOPE_BYTES`, with closed keys and
bounded candidate/binding collections. The provisioner reads once by
`operation_id` and resolves plan images/bindings from that in-memory snapshot.
A registry, binding, or backend change after launch affects a later generation,
not a retry of the current one.

## ACES Results, Ordering, And Apply

Extend the existing `shared.operation_results` contract rather than adding an
ACES inbox, event family, result envelope, status enum, or exception hierarchy.
The closed `(resource="aces-range", operation)` step table must represent the
legal observations for provision and destroy, including terminal failure.

ACES-specific result payloads compose, rather than replace:

- the ACES operation-state vocabulary and pure mapper in
  `shared.aces.status`;
- the bounded runtime resources produced by
  `aces_snapshot.snapshot_resources`;
- the write-boundary validation in `shared.schemas.aces_operation`; and
- the idempotent persisters in `shared.aces.operations`.

Result-step ordering is authoritative for transport. Do not use thread
completion order, a random event UUID, or producer wall-clock time as the inbox
ordering/idempotency key. When an ACES sidecar needs `source_timestamp` or
`captured_at`, derive it from the accepted inbox row's stable database
timestamp (or another value guaranteed stable for that semantic step). Calling
`datetime.now()` while rebuilding a retried result changes its digest and turns
a harmless replay into a conflict.

The applier must preserve both idempotency layers:

1. inbox identity/digest and `(operation_id, result_step)` conflict detection;
2. `AcesOperationRecord`'s canonical payload digest, deterministic idempotency
   key, retention stamp, and timestamp ordering.

The existing `_aces_status` orchestration and `_aces_evidence` event consumers
are compatibility paths, not the authoritative apply seam: calling them from
the applier would enqueue another outbox workflow and separate sidecar/domain
writes from result disposition. Reuse their pure mapper and
`shared.aces.operations` persisters inside the applier transaction instead.

For a lifecycle-changing result, Range state, result disposition, strict system
audit, ACES status evidence, and the standard notifications commit together.
Provision success retains the normal status/provisioned notifications; destroy
success retains status/destroyed notifications. Snapshot persistence is
operational evidence, not a lifecycle action: it remains excluded from
`AuditLog` and from notification payloads, as enforced by
`test_operation_record_audit_boundary.py`.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| User authorization and feature gate | `cms.services._aces_range_create`, generic Range destroy/lifecycle services, `SHIFTER_ACES_NATIVE_PROVISIONING` | Results never prove user authority and do not create a callback/API surface. |
| Generation and command shape | `engine.launch_intents`, `engine.ecs`, `ProvisionerLaunchIntent`, `Range.provisioner_operation_id`, `main.py` | Require the canonical generation for authoritative ACES work; do not keep `request_id` as the generation. |
| Input persistence | `OperationInput`, `_materialize_operation_input`, `shared.operation_envelope` | One exact-id immutable row; no latest-by-request read, ORM dump, or table/query language. |
| ACES plan | `shared.aces.runtime_target`, `aces_plan.parse_plan`, plan parity/conformance tests | Keep the serialized ACES plan; do not add a Shifter-owned duplicate plan schema. |
| Content delivery | `shared.aces.content_delivery`, `aces_delivery_contract`, `aces_content_delivery` | Reuse `DeliveryBinding` validation and completeness checks; transport no bytes or access credentials. |
| Image resolution | `engine.services._aces_image`, `shared.aces.image_policy`, `aces_gce_image` | Project allowlisted candidates; keep matching/passthrough/fail-loud policy in the existing resolver. |
| Backend ownership | `_range_backend_binding`, `shared.range_instantiation_policy`, `range_backend_evidence` policy | Resolve from Engine-owned evidence and project only the normalized outcome; never transport raw state or guess. |
| Result transport/apply | `shared.operation_results`, `provisioner_db_appends`, `_operation_apply`, `_operation_apply_domain` | Extend the closed step contract and the one applier; preserve digest, generation, ownership, ordering, and transaction controls. |
| ACES evidence | `shared.aces.status`, `shared.aces.operations`, `shared.schemas.aces_operation`, `aces_snapshot` | Preserve mapping, redaction, size, idempotency, timestamp, retention, and presentation contracts. |
| Audit/notifications | `shared.audit`, `_operation_apply_effects`, ADR-025 message constants and `RangeEventOutbox` | Strictly audit lifecycle changes; keep snapshots out of audit and events. |
| Errors/logging | `shared.errors`, `shared.api.errors`, provisioner `log_redact`, platform `shared.log_sanitize` | Fixed reason codes and bounded value-free diagnostics only; no new hierarchy or raw exception persistence. |
| Recovery/observability | `apply_operation_results`, launch/result workers, sidecar prune worker | Reuse worker locks, retry, heartbeat, retention, and dispositions; add no ACES worker/queue. |

## Cross-Cutting Security Layers

The design passes these layers in order:

1. **External authorization and admission.** Existing session/token
   permissions, CMS user validation, active-range reservation, launchability,
   feature flag, backend admission, and owner checks authorize the request.
   Phase 5 adds no endpoint, token, scope, callback, or cloud principal.
2. **Launch and argv shape.** `validate_provisioner_command` and
   `command_from_payload` accept only the resource/operation and request and
   operation UUIDs. Plan, bindings, images, backend evidence, status,
   diagnostics, credentials, and environment maps never enter argv. A cut-over
   ACES cloud mutation must fail closed when no canonical operation id/input is
   available; the local subprocess path must use the same contract rather than
   silently falling back to event/direct-table behavior.
3. **Input wire validation.** Engine validates before materialization; the
   provisioner selects the exact operation row, validates the outer envelope,
   compares flattened discriminators, and invokes the composed plan,
   `DeliveryBinding`, image-candidate, and backend validators before cloud or
   guest mutation. `JSONField`, dataclasses, `TypedDict`, and model constraints
   are not runtime parsers.
4. **Result wire validation.** The producer parses the closed result payload
   before append. The applier revalidates envelope, flattened columns, version,
   digest, result kind/step, payload, sibling conflict, legal order, current
   generation, request ownership, and target state before persistence.
5. **Database authentication and privilege.** Continue through
   `provisioner_db.get_db_connection`, provider DB-auth adapters, TLS/IAM or the
   existing local password mode, and the portal runtime role for the applier.
   The provisioner keeps exact input `SELECT` and inbox/sequence append only;
   it gains no sidecar, domain-table, or inbox-read capability.
6. **Secrets and persisted shapes.** Continue through provider secret stores,
   `shared.cloud.sensitive_env`, ACES guest-secret helpers, content-addressed
   bindings, and ACES sidecar secret-key/size validation. Inputs/results may
   carry the already-approved reference shapes, never secret values, DB tokens,
   private keys, signed URLs, guest commands/output, raw provider responses, or
   sensitive environment maps.
7. **Configuration and runtime rendering.** This cutover needs no new setting,
   environment variable, IAM permission, port, Terraform input, Helm value, or
   Kubernetes field. Existing ACES flags/retention settings,
   `config/env-manifest.json`, installation runtime inventory, AWS task
   definition, GCP renderer, and admission allowlists remain authoritative.
8. **OS/process exposure.** Payloads remain in the database boundary, not shell
   strings, process titles, temporary files, Terraform CLI variables,
   Kubernetes literal env, workflow output, or child-process argv. Existing
   secret-backed environment values must not be copied into results or logs.
9. **Logs and error envelopes.** Log safe operation/result correlation,
   contract version, step, disposition, status, counts, and fixed reason codes.
   `safe_log_value` prevents injection but is not confidentiality redaction;
   current `logger.exception` formatting includes a full stack trace. Raw
   provider/parser/SQL exceptions and payload fragments must therefore not
   cross the ACES result/log boundary. Public/DRF errors remain under
   `shared.api.errors`, and Range errors/events/audit use bounded authored
   values only.
10. **Durable projections and recovery.** The applier transaction owns domain
    state, sidecar evidence, strict lifecycle audit, notification intent, and
    disposition. ADR-025 drains notifications afterward; Mission Control and
    CMS reconciliation remain projections. A missing result is recovered by
    idempotent re-drive/provider reconciliation, not by replaying an ACES event.

The shared provisioner DB role remains a workload-wide trust boundary, not
per-range isolation. Generation and ownership checks contain stale or
misdirected results but do not make a compromised role tenant-scoped.

## Grants And Rolling Cutover

Use forward migrations and real PostgreSQL effective-privilege tests.

- Revoke the explicit `engine_aces_content_delivery_binding` `SELECT` once no
  launched compatible task can use it.
- Prove `engine_aces_image_mapping` direct `SELECT` is absent after cutover,
  including grants inherited or applied outside the model-creation migration;
  do not assume the lack of a visible historical grant is proof.
- Moving `range_backend_evidence` removes that call site's need for
  `engine_instance`/`engine_request` reads, but those table-level grants cannot
  be revoked in this phase if NGFW or uncut cyberscript paths still read them.
- Likewise, `mission_control_range` and range-event-outbox privileges survive
  only where an active uncut family still requires them. Do not over-revoke and
  break that family, and do not cite its use as a reason to retain a dedicated
  ACES binding/image grant.

Tests must prove both sides: the removed ACES reads fail under
`provisioner_lambda`, while exact operation-input reads, inbox appends,
identical replay, conflicting replay disposition, and Engine applier/sidecar
writes still work under their real roles.

## Extensibility Seam

The seam remains the one versioned operation contract, parameterized by
`resource`, `operation`, and canonical `operation_id`. Within the ACES input,
backend/provider and image candidates are explicit data keyed by
`(provider, source_name)`. Within results, closed step/state mappings select the
existing ACES evidence contracts.

The next provider or ACES contract version should add one provider/profile
adapter and compatibility entry without adding a table grant, new inbox,
ACES-only worker/event bus, second plan/status/snapshot schema, or edits to CMS,
CTF, and Mission Control consumers.

## Whole-Repo Scope

Implementation must evaluate these surfaces together:

- operation boundary: `engine/launch_intents.py`, `engine/models/_operation_io.py`,
  `engine/services/_operation_apply*.py`, `engine/ecs/`, the applier management
  command, and Engine migrations;
- ACES Engine services/models: `_aces_range.py`, `_aces_status.py`,
  `_aces_evidence.py`, `_aces_image.py`, `_aces.py`, and ACES sidecar
  projections;
- shared contracts: `shared.operation_envelope`,
  `shared.operation_results`, `shared.aces.{runtime_target,content_delivery,
  image_policy,status,operations}`, `shared.schemas.aces_operation`,
  `shared.range_instantiation_policy`, `shared.audit`, `shared.errors`, and
  `shared.log_sanitize`;
- provisioner: `main.py`, `aces_range_ops.py`, `provisioner_db_aces.py`,
  `provisioner_db_appends.py`, `range_backend_evidence.py`, `aces_plan.py`,
  `aces_snapshot.py`, content/image resolvers, `events.py`, `log_redact.py`,
  and provider realization/destroy paths;
- downstream/recovery: `RangeEventOutbox`, Engine/CMS handlers,
  `reconcile_range_events`, Mission Control ACES projections, CTF bridge,
  operation-result worker, and ACES sidecar prune worker;
- runtime/security: DB-auth adapters, `shared.cloud.sensitive_env`, ACES secret
  helpers, AWS/GCP task renderers, provisioner Job admission, env manifest,
  runtime inventory, service accounts/RBAC/network policy, and container
  logging;
- evidence: shared operation/ACES schema tests, ACES plan parity and
  conformance, provisioner ACES orchestration/content/image/backend tests,
  applier transaction/ordering tests, PostgreSQL grant tests, import-linter,
  ADR guard, and provider render tests when touched.

## Gotchas And Anti-Patterns

- Do not keep using `request_id` as the new ACES generation or result identity.
- Do not read “latest input by request”; retries consume their exact immutable
  generation even after registry or backend changes.
- Do not pass `user_id`, payload-owned ownership, ORM joins, arbitrary state,
  raw backend evidence, or registry management metadata through the input.
- Do not use the legacy integer `range_id` to select or authorize Engine rows;
  it is only a reconstructive cloud/secret naming key in this compatibility
  slice.
- Do not pre-resolve images into a second image policy or copy
  `resolve_from_candidates`; project candidates and reuse the existing resolver.
- Do not duplicate `DeliveryBinding`, ACES plan, runtime snapshot, status,
  reason-code, exception, sanitizer, or retry schemas.
- Do not emit both ACES outbox events and operation results for one generation,
  or call the legacy ACES event consumer from the authoritative applier.
- Do not make a producer timestamp part of a deterministic result payload
  unless retries reproduce it exactly.
- Do not let a snapshot create lifecycle audit, a range event, or mutable
  runtime state; it is bounded evidence only.
- Do not let a late `running`, snapshot, or failure overwrite a terminal result,
  and do not persist evidence for a stale/wrong-owner generation as though it
  were current.
- Do not raise the envelope or snapshot limits merely to carry the full image
  registry or provider output.
- Do not swallow authoritative append, sidecar validation, audit, or outbox
  failures. Transaction rollback must leave the inbox row retryable.
- Do not log `str(exc)`, full stack traces, result/input payloads, storage
  references requiring masking, provider bodies, SQL, or guest output on normal
  ACES failure paths.
- Do not edit historical grants or revoke shared table privileges while an
  inventoried uncut caller still needs them.

## Non-Goals And Implementation Boundaries

- No ACES plan/SDL, content materialization, image matching, GCE realization,
  guest setup, secret lifecycle, Terraform/provider, or cleanup redesign.
- No new public API, callback, user auth/scope, feature flag, environment
  setting, cloud IAM role, event bus, queue, worker, repository layer, or
  workflow engine.
- No redesign of Mission Control ACES read projections, CMS/CTF range
  projection, sidecar retention/pruning, or ADR-025 notification delivery.
- No redesign of the accept-time, request-scoped ACES `operation_receipt`
  contract; it is not a provisioner result or lifecycle fence.
- No historical sidecar rewrite from request-scoped operation ids to canonical
  generations.
- No final removal of domain/outbox grants still required by later #478
  families; this phase removes only capabilities made unused by its actual
  cutover.

## Validation Expectations

For this architecture note:

```bash
python3 scripts/adr_guard/adr_guard.py --files docs/architecture/provisioner-persistence-phase5-preflight-1837.md --level fast
```

Future implementation touching architecture, workflows, or
`shifter/shifter_platform` must also run the full ADR guard and the
stack-native/subsystem checks required by `AGENTS.md`.
