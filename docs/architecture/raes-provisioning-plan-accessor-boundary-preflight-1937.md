# RAES ProvisioningPlan accessor boundary decision (#1937)

Status: accepted architecture decision. This record changes no provisioning
behavior, dependency, schema, deployment, or workflow.

This decision refines, but does not replace, [ADR-024](raes-migration-adr.md),
ADR-032 in `docs/adr/index.yaml`, the transport guidance in
`aces-provisioning-plan-transport-preflight-1522.md`, or the current standalone
reader in `shifter/engine/provisioner/raes_plan.py`. It evaluates the public
Python accessor delivered by
[OpenRAE/rae#713](https://github.com/OpenRAE/rae/issues/713) and merged in
[OpenRAE/rae#1041](https://github.com/OpenRAE/rae/pull/1041). The accessor first
shipped in `raes==3.3.0`; Shifter's current `raes==2.0.0` pin predates it.

## Decision

Select direction 1: retain the version-gated plain-data reader and its parity
fixtures. The Shifter provisioner does **not** install or import `raes`,
`raes_contracts`, or the rest of the RAES Python module family.

The provisioner is a separate, dependency-light deployable and its trust input
is serialized data, not Python object identity. A helper on `PlannedResource`
can make in-process access safer, but using it in the provisioner would require
reconstructing a RAES object from untrusted serialized data before the
Shifter-owned transport and shape checks have succeeded. It would therefore add
a runtime/supply-chain dependency without replacing the cross-process validator.
It would also violate ADR-024 and ADR-031-R1's import boundary.

After Shifter upgrades to a released, pinned RAES version containing the #713
API, `shared.raes` may use its public accessors for typed in-process access and
parity evidence. That is an internal producer-side improvement, not a boundary
change. Direction 4 is not selected now: a separately published serialized
projection, schema, or version-pinned fixture corpus would be a stronger
wire-shape oracle only if public accessor, compiler, conformance, and exact-pin
serialized-fixture evidence proves insufficient. Shifter makes no claim that
RAES's raw `resources` mapping is a general public wire protocol. It supports
that mapping only inside `raes-provisioning-plan-v1`, for the exact accepted
RAES producer release.

Direction 2 is rejected because it couples the privileged deployable to the
monolithic RAES Python distribution and its broader dependency graph while
leaving serialization validation unsolved. The released accessor is not a
standalone wire-reader package.
Direction 3 is rejected because a separately versioned realization projection
would be the second provisioning contract prohibited by ADR-032-R3. The frozen
`RaesPlan*` values are allowed only as a process-local, post-validation
realization view; they are not a DTO, API, authoring model, or persistence
schema.

## Contract and ownership

| Concern | Authoritative input and owner | Boundary rule |
| --- | --- | --- |
| Authored and compiled meaning | The typed RAES `ProvisioningPlan` produced by the exact pinned RAES compiler; RAES owns its semantics. | Shifter must not infer authored source, resources, infrastructure, names, or references from provider state or scenario identity. |
| Backend admission | `shared.raes.runtime_target.interpret_provisioning_plan`, the public RAES diagnostics/conformance surfaces, and Shifter's declared capability envelope. | This proves the typed plan is within Shifter's advertised capability before dispatch; it does not make persisted bytes trusted. |
| Serialization | `shared.raes.runtime_target.serialize_provisioning_plan`; Shifter owns `kind`, `contract_version`, the exact `raes_version` stamp, and JSON-safe transport. | RAES provisioning resources are copied, not re-modelled. Non-JSON values must not acquire meaning through best-effort stringification. |
| Persistence and generation transport | `engine.models.Range.range_config` is the persisted plan; `shared.operation_envelope`, `shared.raes.operation_input`, and the immutable `OperationInput` row own the generation-fenced execution input. | The provisioner selects the exact `operation_id`, binds it to `request_id`, and never falls back to current ORM state or a second plan table. |
| Serialized structural validation and payload access | `shifter/engine/provisioner/raes_plan.py` and its existing split helpers own defensive parsing for the standalone consumer. | Validation completes before a `RaesPlan` is returned. No other provisioner module traverses raw RAES payload paths. |
| Backend policy | Existing Shifter admission, artifact/image resolution, machine defaults, naming, network realization, egress/firewall policy, lifecycle, and provider apply modules. | A RAES accessor reports authored structure; it never selects a provider image, machine type, subnet, credential, admission result, or cloud effect. |

The semantic oracle and the wire oracle are deliberately distinct. Public
#713 accessor behavior can define what a typed resource means. It cannot, by
itself, prove how that resource was serialized or that a received envelope is
authentic, supported, complete, and internally consistent.

## Fail-closed interpretation

The consumer must select the `(contract_version, raes_version)` compatibility
profile before reading any resource payload. Missing or malformed `kind`,
contract version, producer version, `resources`, resource entry, address,
domain, resource type, or payload is a hard failure. A resource whose map key
does not equal its embedded address, whose domain is not `provisioning`, or
whose type is unknown or wrong for an accessor is also a hard failure.

For supported resources, absence and malformation are not equivalent:

- An omitted optional authored source or sizing value may become `None`; the
  existing backend policy then supplies an already-documented default or fails
  because it cannot realize the omission.
- An omitted count may retain the RAES-defined default of one. A present count
  of the wrong type or outside the accepted range must not be coerced to one.
- An omitted or blank logical name has the neutral fallback of the full
  canonical compiled resource address, matching the released public accessor.
  A present non-string name is malformed, not absent. The standalone reader's
  current leaf-only fallback is a compatibility gap owned by #2082; this
  decision does not change it.
- Optional lists may be empty when omitted. A present non-list, blank member,
  wrong member type, or unresolved reference is malformed and must not be
  filtered into an empty list.
- A missing optional network gateway may remain absent. A provider-required
  value such as the GCE subnet CIDR may be rejected by provider-plan validation;
  a present malformed value must fail earlier as malformed structure.
- Non-empty `refresh_dependencies` may not be silently ignored. They require an
  explicit admitted realization meaning or a hard unsupported-term failure.
- Duplicate addresses or aliases; dangling network, ACL, composition, account,
  feature, domain, and ordering references; inconsistent topology identities;
  and unsupported account/domain/service terms remain hard failures.

These rules preserve legitimate RAES omission and Shifter backend defaults
without turning wrong types, unknown terms, or version skew into defaults. They
also identify current soft-accessor behavior (`_mapping`, count fallback,
filtered reference lists, malformed source/resources becoming `None`, and
`json.dumps(..., default=str)`) as compatibility risks to cover in follow-up
issues, not behavior to change in this decision-only issue.

Logical names remain provider-neutral data. Conversion to a GCE-safe resource
name belongs only at the existing `gcp_range_cell_naming._short_resource_name`
boundary. The compiled address remains the stable identity and idempotency key;
neither a display name nor its provider-safe spelling may replace it.

## Cross-cutting incumbents and gates

The eventual follow-ups must reuse these boundaries rather than adding parallel
schemas, validators, errors, or workflows:

- **Authentication and launch authority:**
  `cms.services._raes_range_create` reuses user/scenario checks, workspace
  admission, active-range reservation, backend admission, audit, and the public
  `engine.services` facade. Serialized plans are not a new public upload or API
  input.
- **RAES semantic validation:** `shared.raes.runtime_target`,
  `_runtime_target_envelope`, `composition_envelope`, `domain_topology`,
  `network_family`, the backend manifest, and RAES-owned conformance remain the
  producer-side semantic/capability gates.
- **Transport and persistence:** `cms.raes.dispatch`,
  `engine.services._raes_range`, `engine.launch_intents`,
  `shared.operation_envelope`, `shared.raes.operation_input`, and
  `provisioner_db_operation_input` retain their exact-key, UUID, size, bounds,
  operation-generation, and no-fallback checks. No new plan table or repository
  is introduced.
- **Secrets and sidecars:** content delivery, participant access, and artifact
  satisfaction remain separately versioned, byte-free bindings validated by
  their existing `from_transport` parsers. The plan must not gain credentials,
  private keys, signed URLs, provider configuration, secret values, generated
  commands, or raw content bytes.
- **Backend policy:** `shared.raes.image_policy`,
  `shared.raes.operation_input.image_lookup_key`, `raes_gce_image`,
  `raes_gcp_plan`, `gcp_range_cell_naming`, `raes_gcp_firewall`, and
  `raes_gcp_apply` remain the canonical image, sizing, naming, network,
  firewall, evidence, and mutation path. `load_gce_range_cell_config` and
  `evaluate_gcp_backend_admission` remain the typed provider/config gates.
- **Errors and observability:** keep `RaesPlanError` inside the parser boundary,
  use bounded value-free diagnostics and `shared.log_sanitize` / provisioner
  `log_redact`, and let `raes_range_ops._classify_failure`, the closed operation
  result reason codes, and `shared.api.errors` prevent raw parser/provider
  exceptions from reaching persisted status, events, or API responses. Log
  request/operation ids and field locations, never payload bodies.
- **Runtime isolation:** `engine.launch_intents.validate_provisioner_command`
  and the `restrict-provisioner-jobs` admission policy keep argv to the closed
  operation plus UUIDs. The plan is read from the immutable DB projection, not
  argv or environment. Preserve the pinned image, dedicated launcher and
  provisioner service accounts, env allowlists/Secret refs, non-root and
  read-only filesystem posture, drop-ALL capabilities, and bounded writable
  volumes.
- **Dependency/import enforcement:** `.importlinter`, the exact platform RAES
  pin/lock, the provisioner dependency lock, and its Dockerfile must continue to
  prove that only `shared.raes` imports the RAES family and that the provisioner
  image does not install it. Because the standalone provisioner is outside the
  import-linter root-package graph, follow-up enforcement must not assume the
  existing import-linter contract alone covers that deployable.

## Compatibility and upgrade evidence

Every RAES release upgrade must provide all of the following before the new
producer can dispatch or provider mutation can occur:

- exact dependency and lock agreement with the producer version stamp;
- public RAES compiler fixtures exercising source, resources, infrastructure,
  logical-name fallback, networks, composition, domains, services, ordering,
  and every supported resource type;
- public #713 accessor expectations from RAES 3.3.0 onward, after Shifter
  upgrades to a release containing them, compared with the standalone reader
  over the same plans;
- Shifter-owned serialized golden fixtures for the exact transport/version pair,
  including omission, malformed, wrong-resource, duplicate, dangling-reference,
  and version-skew negatives;
- `test_plan_provisioner_parity.py`, provisioner `test_raes_plan.py`, the public
  RAES conformance fixture gate, and live target conformance evidence; and
- an explicit operational choice to drain plans from the old producer or to
  authorize a bounded multi-version read window. A rolling window must never
  appear accidentally by widening a version comparison.

The preferred future wire oracle is an upstream public serialized projection,
schema, or fixture corpus. Until one exists, the compatibility oracle is the
combination of public typed RAES APIs/accessor behavior, public compiler and
conformance fixtures, and Shifter-owned serialized fixtures generated by the
exact pin. Private reference-backend helpers are never an oracle. A public
reference interpreter may be differential evidence only for the behavior it
publicly guarantees; it does not own Shifter policy.

The extensibility seam is the existing transport-version and producer-version
gate. A shape-preserving release replaces or deliberately adds one reviewed
compatibility entry; a shape-changing release gets a new
`raes-provisioning-plan-vN` reader selected before payload access. It does not
require a new DTO, persistence model, service, provider adapter, or authoring
contract.

## Follow-up issue boundaries

The dependency chain is explicit:

1. **Public prerequisite (complete):** OpenRAE/rae#713 and merged PR #1041
   delivered the public typed accessor in RAES 3.3.0.
2. **Boundary decision (this issue):** #1937 fixes ownership, failure, naming,
   compatibility-evidence, and dependency rules without changing runtime
   behavior.
3. **Compatibility and implementation (#2082):** the existing Shifter issue is
   already blocked by #1937 and owns exact `raes`/`raes-env-packs` pair
   assessment, the public-accessor versus serialized-reader parity matrix,
   consumer and enforcement gaps, dependency locks, the drain or bounded
   multi-version-read choice, conformance, and any authorized upgrade.

No additional Shifter follow-up is created by this decision because it would
overlap #2082. If #2082's evidence later shows that the public accessor,
compiler, conformance, and exact-pin serialized fixtures cannot establish wire
compatibility, #2082 must first record the missing evidence boundary before a
separate upstream wire-artifact request is opened.

## Whole-repository scope

The follow-ups must evaluate the producer and conformance modules under
`shifter/shifter_platform/shared/raes/`; CMS launch and `cms/raes/dispatch.py`;
Engine range persistence, launch intents, operation inputs/results, and models;
the provisioner operation-input reader, `raes_plan*`, composition/ACL/service
parsers, range operations, image resolver, GCE plan/naming/firewall/apply path,
and their tests; `.importlinter`; both Python dependency manifests/locks; the
provisioner Dockerfile; the Kubernetes provisioner Job admission policy and its
builder/tests; `docs/adr/index.yaml`; and the repository ADR, layer, lint,
security, and conformance checks selected by those paths.

## Non-goals and anti-patterns

- No provisioning behavior, dependency, serializer, parser, fixture, provider,
  workflow, or deployment change in #1937.
- No reimplementation of OpenRAE/rae#713 and no assumption that its Python
  helper is a serialized wire contract.
- No second authored scenario/provisioning contract, persisted realization
  projection, public DTO, API endpoint, plan repository, or exception hierarchy.
- No provider image resolution, machine defaults, sizing, network allocation,
  firewall/egress, admission, lifecycle, or cloud-effect change.
- No scenario/name/OS sniffing, provider-safe normalization in the RAES
  accessor, best-effort parsing, silent unknown-resource skips, malformed-to-
  absent coercion, private-helper differential contract, payload logging, or
  payload/credential placement in argv, environment, events, or API errors.
- No weakening of version, operation-generation, no-mutation, import-layer,
  dependency-lock, Kubernetes admission, ADR, or conformance gates.
