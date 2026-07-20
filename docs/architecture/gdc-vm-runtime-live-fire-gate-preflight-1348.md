# GDC VM Runtime Live-Fire Gate Preflight

Issue: GitHub #1348, "Gate GDC VM Runtime range backend for live-fire
scenarios."

This is requirement-free pre-implementation guidance. The issue title, body,
and acceptance criteria are the shipping contract. This note does not implement
the gate and is not an implementation plan.

## Decision Boundary

ADR-030 already decides the trust boundary: normal Shifter scenarios are
live-fire, and GDC VM Runtime, scenario Pods, GDC L2 Networks, namespaces, and
NetworkAttachmentDefinitions are not an approved participant containment
boundary. The implementation must enforce that decision; it must not reopen the
containment decision or treat successful GDC scaling as new security evidence.

The current repository has only a realization selector. For
`CLOUD_PROVIDER=gcp`, `get_gcp_range_backend()` and the generated runtime env
default `GCP_RANGE_BACKEND` to `gce`, while an explicit `gdc` value still routes
the generic range provision command through `gdc_range_networks`,
`gdc_vmruntime_assets`, and `gdc_scenario_pods`. That selector answers "which
implementation is configured?" It does not answer "is this backend approved for
this launch purpose?"

Every current Mission Control and CTF range launch is live-fire regardless of
deployment environment, scenario id, user role, or `RangeSource`. Therefore:

- normal GCP range creation may select only an approved GCE VM range-cell
  capability; absent approval or unusable GCE configuration fails closed before
  task dispatch or cloud/subnet mutation;
- `GCP_RANGE_BACKEND=gdc` must never make the normal `range provision` or
  `aces-range provision` workflow eligible for GDC, and GDC must never be a
  retry, rollback, or missing-config fallback;
- retained GDC range infrastructure is development/operator-validation only.
  A future BAS, demo, image-validation, or operator-validation entry point must
  carry an explicit trusted non-user purpose. Until such an entry point exists,
  leaving GDC provision unreachable from generic product range commands is the
  correct fail-closed behavior; and
- destroy remains permitted for already-owned GDC resources. The gate must not
  strand existing namespaces, VMs, disks, secrets, L2 Networks, NADs, or subnet
  allocations.

`RangeSource` remains server-derived provenance (`mission_control` versus
`ctf`) and the single-active-range partition. Both values can create live-fire
ranges, so it is not the instantiation-purpose control. `ENVIRONMENT` is a
deployment tier, not launch authorization. `CLOUD_PROVIDER` selects the backend
bundle, not the GCP range substrate. Do not collapse these concepts.

## Architecture Decisions And Guardrails

- Enforce approval at the CMS service boundary shared by legacy and ACES range
  creation, before `_reserve_active_range_slot`, Engine persistence, launch
  intent creation, subnet allocation, or provider mutation. API/UI hiding,
  workflow variables, and provisioner-only rejection are insufficient primary
  gates.
- Keep a provisioner-side denial as defense in depth. A generic live-fire
  provision command that reaches the GDC route must return the ADR-039
  `identity-or-policy` class without calling any GDC apply function. Missing or
  malformed approved-backend configuration is `prerequisite`, not permission to
  try GDC.
- Preserve the existing structured command family. Backend or purpose must not
  become a user-controlled CLI argument, request-body/query field, scenario
  field, or free-form environment string passed in argv.
- Normalize `GCP_RANGE_BACKEND` and the `GCP_RANGE_PLANE` compatibility alias in
  one dependency-light parser consumable by Django and the standalone
  provisioner. Keep `get_gcp_range_backend()` as the compatibility-facing
  incumbent; do not reproduce `gdc`/`gce` string validation independently in
  CMS, Engine, renderers, and tests.
- Treat backend selection and live-fire approval as separate inputs. The
  `shared.range_cells` `live-fire-vm-range-cell` capability and closed
  provider/backend admission shape are the GCE lifecycle contract, but a
  capability name does not self-attest deployment promotion. ADR-030-R5 escape
  evidence remains required before an environment is event-ready.
- Bind the admitted backend/capability and launch purpose immutably to the
  Engine-owned operation/range state before dispatch. Later provision, destroy,
  retry, and reconciliation must use that binding rather than rereading a
  mutable environment selector. Do not add backend fields to `RangeSpec`, the
  ACES plan, or scenario YAML; those are realization intent, not platform
  admission or resource ownership.
- Gate new provision only. Destroy must route from persisted ownership/backend
  state, including compatibility handling for pre-gate GDC ranges. Pause/resume
  of retained GDC validation assets does not confer live-fire approval and must
  not bypass the provision gate by recreating resources.
- Do not gate GCP/GDC management infrastructure or VM-Series merely because it
  contains "GDC" in its name. The prohibited boundary is participant range
  realization through GDC VM Runtime/Pods/L2 networks. GKE management
  workloads, bootstrap infrastructure, and an NGFW used outside that boundary
  remain separate concerns.

## VLAN Commit Disposition

Retain commit `b8116eef8` ("Use VLAN IDs for GDC range networks") as GDC
development/validation-path maintenance, but do not land or deploy it as an
independent justification for normal range enablement. The GDC modules are
already the non-live-fire path once this gate exists, so moving the VLAN logic
would duplicate network allocation and manifests; reverting it would restore
the duplicate-`vxlan0` admission failure without improving containment.

The VLAN derivation must continue to reuse the canonical allocated subnet CIDR
and `SubnetAllocation`, not introduce another mutable VLAN allocator. Its
`/16`-to-`/28` ordinal mapping has 4,096 possible subnets but IEEE VLAN IDs admit
only 1-4,094; the existing explicit rejection of out-of-range ordinals must
remain. VLAN uniqueness proves GDC admission/scaling behavior only. It does not
prove isolation from the Kubernetes/GDC API, management-plane workloads,
cluster identities, node/kernel compromise, or another participant range.

Any GDC validation document changed with that commit must stop instructing
operators to use the deployed CTF path. Validation should use a dedicated
operator-only path once one exists, and its evidence must be labelled
development/validation rather than live-fire containment evidence.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| HTTP auth and product provenance | Mission Control DRF permissions/scopes, CTF organizer/participant gates, `ctf.bridges.cms_create_range`, `shared.enums.RangeSource` | Keep identity, ownership, and product-source derivation at existing entry points. Never accept backend or purpose from the request. |
| Range admission | `cms.services.create_range_dispatch`, `_range_create`, `_aces_range_create`, active-range reservation helpers | Use one service-level backend-policy check for both realization paths and direct service callers. Reject before the DB reservation/dispatch side effects. |
| Scenario and transport validation | CMS scenario registry/hydrator, `RequestSpec` / `RangeSpec`, persisted-envelope validation, ACES plan validation, `shared.range_cells` | Do not add a provider/mode field or duplicate scenario DTO/validator. The GCE request remains closed, versioned, and digest-bound. |
| Configuration binding | `get_gcp_range_backend`, `config._runtime_env`, `scripts/gcp/render_runtime_env.py`, `installation.runtime_inventory`, `config/env-manifest.json`, backend published contract | Reuse the current selector and compatibility alias, but validate it once for every consuming process. Unknown/blank deployed values fail closed. |
| Engine workflow and delivery | Engine `Range`/`Request`, `engine.services._range`, `ProvisionerLaunchIntent`, `engine.ecs`, `GCPTaskRunner` | Persist trusted admission/ownership state before dispatch. Preserve request-id correlation, operation generation, structured argv, and durable launch authorization. |
| Provisioner routing | `terraform_ops.run_range_terraform`, `terraform_vars.build_range_variables`, `range_terraform_runner` | Keep one range lifecycle entry point. Add denial before GDC apply calls; do not create a second GDC runner or controller. |
| Persistence and cleanup | Engine range/instance/subnet state, `state_helpers`, `provisioner_db`, `SubnetAllocation`, range-event outbox/reconciler | Persist backend ownership once and route cleanup from it. Keep secret references only and retain recovery evidence until resource absence is observed. |
| Errors and retries | `CMSError`, `CTFError.code/details`, `shared.api.errors`, `shared.errors`, ADR-039 failure codes | Use an authored stable policy code/message. Do not add a provider exception hierarchy, return raw `str(exc)`, or retry a permanent policy denial in CTF batch/spare/recovery flows. |
| Logs and audit | `shared.log_sanitize`, provisioner `log_redact`, existing range audit events and structured request/range ids | Log decision, normalized backend/capability, trusted purpose, source, and stable code. Do not log scenario payloads, config maps, kubeconfig data, provider responses, or credentials. |
| Secrets and task admission | provider secret stores, `shared.cloud.sensitive_env`, ephemeral per-Job Secrets, both `restrict-provisioner-jobs` admission-policy copies | The selector/purpose are public configuration; secret values remain Secret-backed. Any new env key must pass forwarding, sensitivity, ConfigMap equality, admission allowlists, and parity tests. |
| GDC validation substrate | `gdc_range_networks`, `gdc_vmruntime_assets`, `gdc_scenario_pods`, `load_gdc_network_access_config` | Retain for explicit validation and cleanup only. Continue Secret Manager kubeconfig loading, deterministic ownership labels, idempotent delete, and canonical subnet allocation. |
| GCE live-fire boundary | `shared.range_cells`, GCE plan/resource modules, range escape validation, ADR-030/039 | The approved path remains private GCE range cells with provider network, firewall, identity, metadata/API, management-ingress, and escape controls. |

## Cross-Cutting Security Layers

- **Authentication and authorization:** Mission Control session/API-token
  permissions and CTF organizer/participant gates run first. The CMS service
  gate is the authorization backstop for internal, scheduled, spare, recovery,
  management-command, legacy, and ACES callers. `RangeSource` is accepted only
  from trusted server code.
- **Request and scenario shape:** Mission Control/CTF serializers validate user
  input; CMS validates scenario/agents and hydrates through the existing schema;
  Engine accepts `RequestSpec`/`RangeSpec` or the validated ACES plan. No public
  schema gains backend, approval, or validation-mode fields.
- **Policy/config shape:** cloud provider, range backend, admitted capability,
  and trusted purpose are closed normalized values. Invalid selectors, missing
  approval, GDC plus live-fire, or approval/selector mismatch fail before any
  reservation, task, subnet, Secret Manager, Compute, or Kubernetes mutation.
  `ENVIRONMENT=development` alone is never sufficient authorization.
- **Persistence and replay:** the admitted backend/purpose is Engine-owned
  immutable operation state, separate from the scenario artifact. Retries and
  destroy cannot silently switch adapters after a redeploy changes
  `GCP_RANGE_BACKEND`; old GDC ownership remains destructible.
- **Task and OS exposure:** `engine.launch_intents` continues to allow only the
  canonical operation plus request/range identifiers. Public backend/purpose
  configuration may be a validated environment binding, but no credential,
  kubeconfig, config blob, provider inventory, or secret reference belongs in
  process argv. Existing GDC `kubectl virt` fallbacks must keep argv arrays,
  restrictive temporary kubeconfig files, cleanup, and bounded execution.
- **Kubernetes admission/runtime:** `GCPTaskRunner` continues to pin image,
  service account, command grammar, environment equality, non-root/read-only
  runtime posture, and writable volumes. Base and Helm admission policies and
  their structural tests must stay equivalent if the environment contract
  changes.
- **Secret handling:** `GDC_ACCESS_SECRET_ID` remains a non-secret reference;
  its kubeconfig payload is fetched through the secrets adapter and must never
  enter logs, events, DB JSON, or user errors. DB/field/DC secret values keep
  using the ephemeral Secret-backed Job env path. The new policy state contains
  no secret material.
- **Cloud/range boundary:** GCE admission still passes the closed
  `validate_gcp_vm_range_cell_request` parser and GCE config/resource validators
  before mutation, then the escape-validation readiness gate. GDC VLAN/NAD/VM
  validation cannot satisfy or bypass those controls.
- **Error envelopes and retries:** HTTP surfaces use `shared.api.errors` and
  authored fixed messages; CTF uses its existing stable error code/details;
  provisioner failures map to ADR-039 codes and bounded event messages. Raw
  exception strings, Kubernetes stderr, provider payloads, CIDR inventories,
  and secret references must not cross API, notification, websocket, or range
  event envelopes. A policy denial is permanent and must not enter the current
  exponential-backoff loop.

## Extensibility Seam

The required seam is a trusted, closed instantiation-purpose/capability result
next to the selected backend in ADR-039's operation context. The minimum policy
distinction is normal `live-fire` versus explicit non-user validation; it is
orthogonal to `RangeSource`, `ENVIRONMENT`, cloud provider, and scenario type.

That seam lets a later ADR approve a new backend, or lets BAS/demo/image
validation add an operator-only purpose, by changing one policy mapping and its
conformance evidence. It must not require new CTF/MC workflows, scenario fields,
provider branches, or booleans such as `ALLOW_UNSAFE_GDC`. A boolean enable flag
cannot express who/what is allowed and would turn a temporary escape hatch into
an apparent safety approval.

## Whole-Repository Surfaces In Scope

The future implementation must account for all of these surfaces, even when a
particular file does not need modification:

- architecture and operator truth: ADR-030, ADR-039,
  `docs/architecture/range-isolation-model.md`, this note,
  `docs/dev/gcp-range-cell-deploy.md`, `docs/dev/deploy-secrets.md`,
  `docs/technical/architecture.md`,
  `docs/technical/platform_infrastructure/gdc-provisioning.md`, and GDC image
  validation docs;
- deployment/config: `.github/workflows/_gcp-dev.yml`,
  `scripts/gcp/render_runtime_env.py`, `scripts/bootstrap/gcp_control_plane.py`,
  `installation.runtime_inventory`, the published backend contract, Django env
  manifest/settings, and renderer/inventory parity tests;
- product admission: Mission Control range API/views, CTF participant, batch,
  spare, and recovery services/bridges, CMS legacy/ACES range creation, and
  management commands that launch ranges;
- orchestration/state: Engine range creation/models/migrations, launch intents,
  ECS/GCP Job dispatch, status events, outbox, and reconciliation;
- provisioner: config, `terraform_ops`, `terraform_vars`,
  `range_terraform_runner`, state writers, GDC network/VM/Pod modules, GCE
  range-cell contracts, and error/redaction helpers; and
- host/runtime enforcement: GKE provisioner Job RBAC, both admission-policy
  manifests, Pod Security/runtime context, ephemeral Secret env routing,
  temporary kubeconfig handling, and GDC/GCE cloud IAM/network boundaries.

## Required Future Evidence

- Default/explicit GCE normal launches are admitted only when the live-fire
  capability is approved; invalid or incomplete GCE config fails without GDC
  fallback.
- Explicit GDC selection rejects Mission Control, CTF participant, batch,
  spare, recovery, legacy, and ACES provision before DB reservation, task
  dispatch, subnet allocation, or any GDC/GCE apply call.
- The provisioner independently refuses a generic GDC provision command, and
  the permanent policy error is not retried or copied raw into user/event
  payloads.
- Existing GDC ranges remain destroyable from persisted ownership after the
  deployment selector changes to GCE, including repeated destroy and
  partial-create cleanup.
- Selector/config tests cover default, compatibility alias, normalization,
  unknown values, and cross-process renderer/Django/provisioner parity. Job
  admission tests remain synchronized if the env shape changes.
- VLAN tests prove deterministic IDs, range limits, and reuse of allocated
  CIDRs, while docs/tests make no live-fire containment claim.
- Operator docs and runtime errors identify GCE VM range cells as the supported
  GCP live-fire backend and GDC VM Runtime as development/validation only.

## Gotchas And Anti-Patterns

- Do not use `GCP_RANGE_BACKEND=gdc` as a one-line rollback when GCE is
  unhealthy. Availability failure must not downgrade containment.
- Do not gate only CTF; Mission Control scenarios and agents also execute
  arbitrary activity. Do not gate only the UI/API; schedulers, spares,
  recoveries, management commands, and direct services must share the gate.
- Do not gate destroy, infer cleanup from the current environment, or discard
  backend ownership after a failed create.
- Do not treat `RangeSource.CTF`, `ENVIRONMENT=production`, a scenario id, a
  VLAN id, a namespace, or a successful VM boot as evidence of containment.
- Do not add backend/purpose to user DTOs, `RangeSpec`, ACES plans, scenario
  YAML, argv, events, or public status enums.
- Do not add a second selector, validator, GDC workflow, repository, event
  family, exception tree, logging helper, or subnet/VLAN allocator.
- Do not catch a policy denial as a generic transient error: current CTF retry
  and notification paths can otherwise retry every participant and leak raw
  nested exception text.
- Do not allow the GCE capability constant, backend-bundle maturity, or a
  configured image to self-certify event readiness; retain ADR-030-R5 evidence.
- Do not rewrite historical changelog entries as current operator guidance.
  Correct live runbooks, workflow comments, and technical architecture docs.

## Non-Goals And Implementation Boundaries

- No runtime gate, code implementation, migration, test implementation, formal
  Ground Control requirement, or implementation plan in this note.
- No new approved containment model and no relaxation of ADR-030.
- No removal of GDC bootstrap, VM Runtime image build, VM-Series, validation,
  or cleanup capabilities.
- No design of the future BAS/demo/image-validation product workflow; #1354
  owns the durable instantiation-policy expansion.
- No redesign of GCE range-cell firewalling, escape validation, scenario
  realization, ACES cutover, AWS range behavior, public lifecycle status,
  task delivery, eventing, access brokering, or secret storage.
