# Scenario-to-GCP Range-Cell Contract Preflight

Issue: GitHub #1344, "Define the scenario-to-GCP VM range-cell contract."

Status: pre-implementation architecture guidance. The issue title, body, and
acceptance criteria are the shipping contract. This note does not implement the
contract or prescribe an implementation plan.

## Decision Boundary

The scenario-to-cell handoff is a narrow specialization of ADR-039's
`range-substrate/v1` boundary, not a third scenario or placement schema.

The platform owns the outer containment and lifecycle boundary: trusted backend
selection, cell identity, provider resource ownership and membership, isolation,
convergent lifecycle state, access brokering, and cleanup. A scenario owns the
meaning and composition of what runs inside the cell: VM count and roles,
containers or nested Kubernetes, internal topology, images, services, ports,
DNS, fixed addresses, startup order, and bootstrap behavior.

Platform lifecycle ownership of a VM resource does not transfer semantic
ownership of that VM's purpose to the platform. The platform may enforce cloud
safety invariants on every resource in the cell, but it must not classify
scenario internals into a universal host/container/Linux/Windows/DC placement
taxonomy.

## Contract Guardrails

- Keep `request_id` plus the existing range/generation identity as lifecycle
  correlation. A provider cell resource identifier may be persisted as a
  binding, but it must not become a second public workflow identity.
- Carry the already-validated scenario realization artifact through the existing
  lifecycle with its schema/profile version and immutable intent digest. The
  legacy path remains `RequestSpec` / `RangeSpec`; the ACES path remains the
  serialized, validated `ProvisioningPlan`. Do not translate both into a new
  platform-authored placement model.
- If the ADR-039 operation/result needs a code-level DTO, it is a closed,
  platform-native contract under `shared`, not a CyberScript or ACES model. It
  references the existing realization artifact; it does not re-model it.
- The platform-facing result is limited to canonical non-secret bindings:
  cell/resource identity, stable authored resource reference, cell membership,
  per-range versus shared ownership, achieved lifecycle state, cleanup recovery
  state, and scenario-declared access bindings.
- An access declaration identifies a stable member target and channel/protocol.
  The platform resolves the actual address from provider state, validates the
  target belongs to the caller's ready range, and resolves credentials only at
  the existing access broker. A scenario-supplied arbitrary hostname or secret
  value is not an access binding.
- Scenario information is opaque only to the platform lifecycle layer. It is
  still closed, versioned, size-bounded, and validated by the owning scenario
  contract before mutation. Credentials are prohibited; intentionally
  sensitive scenario content stays inside its owning contract and redaction
  rules. "Opaque" must not mean an unvalidated JSON bag, shell script, provider
  request, or executable blob.
- Scenario readiness is part of the provision postcondition. The public range
  remains on the existing `ResourceStatus` vocabulary and cannot become ready
  until the scenario realizer reports its declared composition and access
  prerequisites usable.
- For a normal GCP user range, the trusted policy result owned by #1354 must
  select an approved live-fire VM range-cell capability. Missing, unsupported,
  or non-live-fire selection fails before participant resource mutation. There
  is no retry or fallback into GDC, GKE, pods, or the management-plane network.
- #1350 consumes this boundary. It must not infer a scenario from names or
  bypass the cell context to create participant resources directly. #1354 owns
  backend approval and selection; #1344 must not create a competing selector.
- Keep AWS and explicitly allowed non-user GCP behavior compatible. This
  boundary does not globally reinterpret the legacy range schema.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Architecture and backend boundary | ADR-030, ADR-039, `provider-neutral-range-substrate.md`, `gcp-range-cell-backend-preflight-1341.md` | Specialize the existing substrate contract; do not publish another GCP lifecycle port. |
| Authorization and workflow | Mission Control permissions/serializers, CTF gates and `ctf.bridges`, `cms.services._range_create`, `RangeSource`, `engine.services._range`, `engine.launch_intents` | Backend/mode context stays server-derived. Preserve ownership checks, active-range admission, operation generation, and the existing command family. |
| Scenario intent | `cms.scenarios.schema` and `hydrator`, `shared.schemas` (`RequestSpec` / `RangeSpec`), `shared.aces.runtime_target`, ADR-031/032 ACES plan transport | Carry one existing validated artifact. Any non-DSL boundary DTO belongs natively in `shared`; do not widen legacy role/OS enums or shadow ACES. |
| Envelope validation | `shared.schemas.persistence.wrap_persisted_spec` / `validate_persisted_spec`; ACES transport validation from #1522 | Validate discriminator, version, payload shape, and digest before projection or mutation. `unwrap_persisted_spec` alone is not validation. |
| Backend config | `shifter/installation` schema/loader/contract/registry/runtime inventory, `scripts/gcp/render_runtime_env.py`, `engine.ecs`, `config.load_gce_range_cell_config` | Reuse root-selected backend configuration and typed GCE settings. Treat `get_gcp_range_backend()` as string parsing, not live-fire approval policy. |
| GCE safety boundary | `gcp_range_cell_plan.py`, `gcp_range_cell_resources.py`, `platform/terraform/gcp/modules/range/vpc`, `platform/terraform/gcp/modules/portal/iam` | Enforce allocated networks, no external IP, approved identities, Shielded VM/metadata posture, explicit ingress/egress, labels, and cleanup ownership regardless of scenario composition. |
| Persistence and reconciliation | Engine `Request`/`Range`/`Instance`/`Subnet`, `state_helpers`, `provisioner_db`, `SubnetAllocation`, ADR-025 range-event outbox/reconciler | Persist intent once and canonical bindings once. Do not add an adapter-specific repository or a third scenario payload column. |
| Secrets and access | provider secret stores, `gcp_guest_secrets`, `shared.cloud.sensitive_env`, `engine.secrets`, `engine.services._terminal` / `_common`, Mission Control Guacamole builders | Persist references only; retain owner/status/membership checks and just-in-time secret resolution. |
| Errors and observability | ADR-039 failure codes, `shared.cloud.exceptions`, `shared.errors`, `shared.api.errors`, `shared.log_sanitize`, provisioner `log_redact`, ECS logging, `shared.audit` | Map failures once, keep user messages authored and bounded, and log correlation/counts/fingerprints rather than payloads or provider responses. |
| Tests and enforcement | existing CMS/Engine lifecycle tests, provisioner GCE tests, access-broker tests, `scripts/adr_guard`, import-linter/layer checks, GCP admission and Terraform policy tests | Extend the current suites; do not create a second contract test harness or weaken enforcement. |

## Cross-Cutting Security Layers

- **Auth and provenance:** Mission Control and CTF authenticate and authorize the
  user before CMS creation. `RangeSource` and the #1354 instantiation-policy
  context are trusted server data, never request-body fields. Engine and access
  services continue to verify request/range ownership.
- **Scenario and transport shape:** scenario YAML passes its existing Pydantic
  schema and hydrator; `RequestSpec` / `RangeSpec` or the ACES plan passes its
  canonical validator; persisted data passes the schema/version validator; the
  substrate projection rejects unknown versions, missing identities, duplicate
  membership, dangling endpoint targets, and digest mismatch before mutation.
  The legacy Pydantic models' default extra-field behavior is not a closed
  outer-boundary contract.
- **Backend approval and config:** #1354 supplies the approved capability result;
  installation configuration, runtime inventory, runtime-env rendering,
  `engine.ecs` env allowlisting, `load_gce_range_cell_config`, and Terraform
  validators remain the config gates. Adding an env key also requires the GCP
  Job admission allowlist and renderer/inventory tests.
- **Task and OS exposure:** the durable launch-intent path and
  `GCPTaskRunner` keep structured argv at `range <operation> --request-id
  <uuid>`. Scenario artifacts, provider state, credentials, secret references,
  bootstrap bodies, and config blobs do not belong in argv, shell strings, Job
  literals, or workflow output. Any file handoff needs bounded private storage
  and cleanup.
- **Cloud identity and network:** participant resources attach only to allocated
  cell networks, with no external IP and no path to pod, service, node, GDC, or
  Kubernetes API networks. Platform policy constrains service accounts,
  metadata/API access, firewall tags, management ingress, DNS, and egress even
  when the scenario owns internal topology. Scenario ownership is not authority
  to relax the outer boundary.
- **Secret handling:** deployment artifacts and boundary metadata carry no
  credential values. Secret material stays in provider secret stores or the
  ephemeral per-Job Kubernetes Secret and only references enter state. Do not
  place scenario data, private keys, passwords, tokens, or token-bearing URLs in
  GCE metadata/startup scripts, DB JSON, events, logs, metrics, or errors.
- **Access brokering:** a declared target must resolve to a persisted member of
  the caller's ready range. The platform chooses the concrete provider address
  and resolves the secret reference at access time. This prevents an endpoint
  declaration from becoming an SSRF or management-plane pivot primitive.
- **Errors, events, logs, and audit:** provider/parser exceptions map to the
  ADR-039 classified failure and existing safe API envelope. Do not pass raw
  `str(exc)` into `publish_failed`; durable events remain minimal
  provider-neutral notifications. ECS logs carry request/range/operation,
  phase, counts, stable codes, and sanitized fingerprints. Existing range
  provision/destroy/access audit events remain authoritative.

## Extensibility Seam

The seam is the existing realization-artifact discriminator/version plus its
immutable digest, paired with an ADR-039 cell context/result. The scenario-owned
realizer interprets the artifact; the platform consumes only provider-safe
resource membership, ownership, lifecycle, and logical access bindings.

A new scenario composition, a second cell in one range, a different internal
orchestrator, or an ACES cutover should add a realization implementation or
artifact version and conformance evidence. It must not require adding another
platform placement enum or editing CMS/CTF lifecycle, public status, event, or
access APIs. Multi-cell membership is the next expected variation, so resource
and endpoint bindings must identify their cell rather than assume exactly one.

## Existing Concept-Conflation Hazards

- CyberScript `AssetSpec.asset_type` (`scenario_pod`, `vm_runtime_vm`,
  `dc_vm`, and related values) is a legacy/GDC scenario DSL. It is not the
  range-cell boundary vocabulary.
- `gcp_range_cell_plan._profile_for_instance`, `_host_access`,
  `_DOCKER_HOST_AMI_KEYS`, role-derived labels/tags, and
  `terraform_vars._build_gce_range_cell_instance` currently translate legacy
  Polaris/role/OS concepts. Keep that compatibility inside a scenario realizer;
  do not expose it as the platform contract.
- `Range.provisioned_instances` and `state_helpers` currently carry `role`,
  `os_type`, and `asset_type` for compatibility. New lifecycle decisions must
  key on stable membership/bindings, not those semantic fields.
- `shared.aces.presentation.RangeAccessChannel` is a read-only UI projection,
  and its current OS-derived channel map is not a lifecycle or endpoint
  declaration contract.
- `unwrap_persisted_spec` only extracts a dict. It does not reject an unsupported
  version or validate the payload. Do not mistake transport convenience for a
  trust boundary.
- `run_range_terraform` currently truncates raw exception text into a failure
  event. New boundary failures need the ADR-039 classification and an authored
  user message, not provider or scenario payload detail.
- `gcp_range_cell_resources._metadata_items` already has a sensitive startup
  metadata surface for guest setup. Do not route new scenario payloads or
  credentials through it; touched handoffs must preserve or improve the secret
  boundary rather than normalize metadata as a deployment bus.

## Anti-Patterns And Non-Goals

- No implementation, formal Ground Control requirement, or implementation plan
  in this note.
- No universal placement enum, per-asset platform taxonomy, scenario-id sniff,
  Polaris-shaped contract, or conversion of every internal container into a
  platform resource record.
- No new `RangeSpec`, ACES shadow model, status enum, workflow/controller,
  repository, event family, validator package, exception tree, secret adapter,
  or access endpoint service.
- No user-selectable backend approval, implicit `gce` approval, environment
  fallback, resource-state sniffing, or GDC/Kubernetes participant fallback.
- No arbitrary provider request, startup script, hostname, IP, port, service
  account, firewall rule, or external network attachment accepted merely
  because it came from a scenario-owned component.
- No platform standardization of internal DNS, ports, fixed addresses, service
  discovery, startup order, bootstrap, nested Kubernetes, or container layout.
- No change to AWS behavior, explicitly authorized non-user GCP modes, #1354
  backend-selection policy, or ACES cutover policy.

## Required Evidence For The Future Implementation

- Two materially different scenario compositions traverse the same boundary
  while the platform never branches on scenario id, role, OS, container, VM, or
  DC category.
- Unknown versions/fields, digest mismatch, duplicate or foreign membership,
  dangling access targets, secret-bearing output, and unsafe provider settings
  fail before mutation.
- A normal GCP user range with no approved VM range-cell capability is rejected
  before task dispatch or subnet/cloud allocation, with no GDC/GKE/pod fallback.
- Access tests prove owner, ready-state, member-target, provider-address, and
  secret-reference checks; isolation tests cover cross-range,
  platform/pod/service/node networks, metadata/API credentials, management
  ingress, DNS, and configured egress.
- Persistence/replay tests cover same-intent convergence, partial-create
  cleanup, repeated destroy, multi-cell membership, and no provider inventory or
  secret material in events and user-visible errors.
