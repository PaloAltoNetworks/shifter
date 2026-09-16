# Normal GCP Scenario Range-Cell Migration Preflight

> **Historical boundary (issue #2062, 2026-08-19):** TechVault is a
> scenario pack. APTL is the former name of LilRAE. The bespoke Shifter
> implementation described here was retired by the RAES hard cut. Exact
> historical commands, paths, symbols, image keys, and workflow names below
> remain factual evidence; they are not current product or integration
> boundaries.

Issue: GitHub #1350, "Migrate normal GCP user ranges to VM range cells."

Status: requirement-free pre-implementation architecture guidance. The issue
title, body, and acceptance criteria are the shipping contract. This note does
not implement the migration or prescribe an implementation plan.

## Decision Boundary

Every normal Mission Control and CTF scenario is live-fire, independent of
scenario id, deployment environment, range source, user role, internal
composition, or whether the scenario happens to use containers. On GCP, all
such launches must cross the existing `shared.range_instantiation_policy`
live-fire gate and the closed `shared.range_cells` GCE VM range-cell boundary.
GDC VM Runtime, scenario Pods, GDC L2 Networks, and the platform pod network are
not fallback containment.

The platform owns admission, the outer cloud-network boundary, cell membership,
provider resource ownership, lifecycle convergence, access bindings, and
cleanup. The scenario continues to own its internal VMs, containers, nested
Kubernetes, topology, ports, DNS, fixed addresses, images, startup ordering, and
bootstrap. Migrating a scenario means supplying an adapter/realizer that can
execute that existing intent inside a cell; it does not transfer scenario
semantics into the platform substrate.

GCP support is not a boolean attached to a scenario name. A launch is supported
only when all of these independent gates pass:

1. the catalog entry is valid, enabled/launchable for the product workflow, and
   its existing scenario contract validates;
2. the trusted live-fire policy admits the GCE backend and that admission is
   bound immutably to the range;
3. the scenario realizer can consume the validated artifact shape without
   approximation or unsupported features; and
4. the selected environment supplies valid images, identities, network mode,
   secrets-by-reference, and other typed GCE prerequisites.

An indeterminate or failing gate is unsupported, never permission to try GDC.

## Normal Creation-Path Inventory

All supported product and operator launch paths must converge before provider
selection:

| Creation source | Canonical path | Guardrail |
| --- | --- | --- |
| Mission Control HTML and DRF API | Mission Control permissions/serializers -> `cms.services.create_range_dispatch` | Do not add a GCP view, serializer, or direct Engine call. |
| CTF participant ranges | CTF participant/event authorization -> `ctf.bridges.cms_create_range` -> `create_range_dispatch` | Preserve event ownership, deadline, and stable CTF error mapping. |
| CTF batch/retry, spare, and replacement recovery | Existing CTF range services -> the same bridge | A permanent policy/unsupported-capability result is not retried or replaced through another backend. |
| Legacy YAML and DB scenarios | `create_range` -> hydrator -> `RequestSpec` / `RangeSpec` -> Engine -> `range provision` | Preserve the digest-bound persisted `RangeSpec`; use the existing legacy GCE compatibility realizer. |
| Registered ACES scenarios | `create_range_dispatch` -> `create_aces_native_range` -> ACES dispatch port -> `aces-range provision` | Preserve ADR-031/032 feature, conformance, plan-transport, and realizability gates; do not translate ACES into `RangeSpec`. |
| Post-deploy and backend validation commands | `run_post_deploy_smoke` / `run_aces_backend_validation` through CMS | These are evidence paths, not alternate provider entry points or live-fire exemptions. |
| Direct Engine service calls | Internal persistence/orchestration boundary only | They must not become a product launch bypass. On GCP, a new live-fire range needs the trusted admission/binding supplied by CMS. |
| AWS operator tooling | Existing CMS -> Engine -> AWS Terraform path | Preserve AWS schemas, variables, IAM, state, setup, and cleanup unchanged. |

The scenario catalog currently includes enabled legacy compositions such as
`basic`, `ad_attack_lab`, `polaris`, and `techvault`, plus NGFW variants and
operator-only smoke scenarios. DB-authored legacy scenarios and registered ACES
packs make the inventory open-ended. Therefore implementation and documentation
must classify supported *shapes and prerequisites*, then report the current
catalog projection; they must not hardcode the checked-in ids as the runtime
authorization source.

Known current capability boundaries must remain explicit:

- GCE has no normal-range NGFW realization today. A scenario requesting NGFW is
  unsupported on GCP/GCE until that adapter capability exists; it must not route
  to the retained GDC VM-Series path.
- An unkeyed legacy guest requires the existing role/OS GCE image profile. A
  keyed guest such as Polaris or TechVault requires an exact complete
  `(profile class, ami_key)` entry whose typed bootstrap capability is supported
  by the GCE realizer. Missing, mismatched, or unsupported mappings fail before
  cloud mutation and never fall back to a generic image.
- A domain-controller composition requires a
  `prepromoted-domain-controller` image profile whose configured DNS and
  NetBIOS identity match the scenario contract. A non-empty image key or generic
  `role=dc` classification is not proof that the scenario can run.
- ACES support is determined by its existing launchability, manifest,
  conformance, plan validation, image-policy, and realization checks. A passing
  legacy adapter says nothing about ACES, and vice versa.
- Disabled smoke scenarios exercise the normal CMS/Engine/provisioner transport
  but are operator validation, not evidence that every enabled user scenario is
  supported.

The operator support matrix is a projection of those facts and real validation
evidence. It may be documented or generated, but it must not become a second
runtime schema or silently mark a scenario supported merely because an image
variable is non-empty.

## Architecture Decisions And Guardrails

- Keep one product admission seam:
  `cms.services._range_backend_admission._assert_live_fire_backend_admitted`,
  shared by legacy and ACES create paths and reached by Mission Control, CTF,
  spares, recovery, smoke, validation, and direct CMS callers.
- Carry the returned `BackendAdmission` beside scenario intent and persist its
  normalized `range_backend` plus `instantiation_purpose` in the Engine `Range`
  create transaction. These fields are platform ownership, not scenario
  metadata.
- After persistence, every provision, compensation, retry, destroy,
  pause/resume, and reconciliation decision must route from that immutable
  binding. `GCP_RANGE_BACKEND` is deployment admission input for new launches,
  not ownership evidence for an existing range.
- In particular, do not let convenience helpers such as
  `is_gce_range_cell_backend()` re-read the environment after an operation has a
  bound backend. Artifact validation, subnet persistence behavior, variable
  shape, apply, compensation, state cleanup, and destroy must all use the same
  operation-scoped backend value.
- Keep `shared.range_cells.build_gcp_vm_range_cell_request` /
  `validate_gcp_vm_range_cell_request` as the only legacy GCE outer request.
  Keep the serialized ACES `ProvisioningPlan` as ACES intent. Do not create a
  common placement DTO between them.
- Keep `gcp_range_cell_scenario` as the legacy `RangeSpec` compatibility
  realizer. Role, OS, `ami_key`, Docker-host behavior, and access conventions
  are scenario-realization details there, not range-cell vocabulary.
- Reuse the adapter's pure validation/planning path for launch-time
  realizability. A missing realizer, unsupported NGFW/topology/guest feature,
  missing image profile, or unusable network mode is an ADR-039
  `unsupported-capability` or `prerequisite` result before provider mutation.
  Do not maintain a duplicate CMS validator that can drift from provisioner
  behavior.
- Surface known catalog non-support early where the existing catalog/
  realizability layer can prove it, but keep the provisioner trust-boundary
  validation authoritative. Catalog feedback is never an authorization bypass.
- A failed GCE preflight or apply may compensate only through GCE using the same
  request/generation and ownership binding. No catch-all handler may retry on
  GDC, translate to scenario Pods, or call the legacy GDC modules.
- Preserve one public lifecycle vocabulary (`ResourceStatus`) and the existing
  status/outbox/reconciliation path. Backend phases and support diagnostics do
  not create a new public status enum or event family.
- Documentation must distinguish:
  supported by contract, configured in this environment, and validated end to
  end. Only the last may claim operational support. Evidence must name the
  scenario/package identity, immutable image/artifact identity, environment,
  backend, and validation date without recording secrets.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Live-fire decision | ADR-030; `shared.range_instantiation_policy`; `_range_backend_admission` | One backend parser and policy result. `RangeSource`, `ENVIRONMENT`, scenario type, and catalog visibility are not containment approval. |
| Outer lifecycle contract | ADR-039; `shared.range_cells`; `gcp_range_cells`; `aces_gcp_apply` / `aces_range_ops` | Reuse the closed request/result and convergent lifecycle. Do not add a scenario-specific GCP controller. |
| Product auth/workflow | Mission Control permissions and serializers; CTF organizer/participant services and `ctf.bridges`; CMS active-range reservation and audit | Keep server-derived user, workspace, source, lease, and purpose. Preserve the database uniqueness backstop and dispatch outside its transaction. |
| Legacy scenario contract | `cms.scenarios.schema`, loader/registry/hydrator; `shared.schemas` `RequestSpec` / `RangeSpec`; persisted envelope helpers | Validate and persist the existing artifact once. Do not add GCP fields to scenario YAML or duplicate the DTO. |
| ACES contract | ADR-031/032; registry launchability; `shared.aces` package, manifest, plan, image, content, and conformance seams | Ride the serialized ACES plan end to end; no CyberScript translation or scenario sniffing. |
| Legacy GCE realization | `gcp_range_cell_scenario`, `gcp_range_cell_plan`, `gcp_range_cell_firewall`, `gcp_range_cell_resources`, `gcp_range_cell_outputs` | Extend the existing adapter only for genuinely supported shapes. Reuse its plan for no-mutation validation. |
| Backend config | `shifter/installation` contract/registry/runtime inventory; `scripts/gcp/render_runtime_env.py`; provisioner `config._gce`; `engine.ecs._env` | Keep one rendered/forwarded/validated config shape and its parity tests. |
| Dispatch and OS boundary | `engine.launch_intents`; launch outbox/drainer; `GCPTaskRunner`; both provisioner-Job admission-policy manifests | Keep request/generation-scoped structured argv, pinned image, exact env equality, and hardened Job shape. |
| Persistence and replay | Engine `Request` / `Range` / `Subnet` / `Instance`; backend binding columns; `SubnetAllocation`; `provisioner_db`; `state_helpers`; ADR-025/043 outboxes | Persist one intent, one ownership binding, and canonical non-secret realized state. Preserve partial-create recovery evidence until absence is observed. |
| Secrets and access | `shared.cloud.sensitive_env`; ephemeral Job Secrets; provider Secret Manager adapters; `gcp_guest_secrets`; Engine terminal/Guacamole access services | Values stay in secret stores or ephemeral Secret-backed env; persistence and range-cell results contain references only. |
| Errors | `CMSError`; CTF stable code/details; `shared.cloud.exceptions`; provisioner `cloud.exceptions`; ADR-039 codes; `shared.api.errors` | Map at existing layer boundaries. Do not add a scenario/backend exception hierarchy or surface raw provider exceptions. |
| Logging/audit/events | `shared.log_sanitize`; provisioner `log_redact`; existing audit vocabulary; notification-only range-event outbox | Log ids, phase, counts, stable codes, and safe fingerprints; never scenario bodies, provider inventories, or credentials. |
| Validation evidence | existing CMS/CTF/Engine lifecycle tests; GCE planner/resource/escape tests; `run_post_deploy_smoke`; `run_aces_backend_validation`; ADR guard/import-linter/admission parity tests | Extend current suites and run a real non-Polaris product-shaped range; do not build a second harness around direct backend calls. |

The portal-side and standalone-provisioner `CloudError` modules deliberately
mirror one provider-neutral family because the provisioner is a separate
deployable. Preserve boundary mapping between them; do not introduce a third
exception tree. `shared.range_cells` currently exposes
`RangeCellContractError` through the shared CyberScript validation exception;
this issue must reuse that incumbent rather than widen the coupling. A later
cleanup may move this non-DSL error natively into `shared`, but that is not a
reason to fork errors during migration.

## Cross-Cutting Security Layers

The intended design crosses every layer below and must satisfy each one.

| Layer | Gate and required behavior |
| --- | --- |
| HTTP/session/token authorization | Mission Control DRF/session/API-token permissions and CTF organizer/participant checks run before CMS. Backend, purpose, workspace, source, and cleanup deadlines remain server-derived and absent from request bodies/query parameters. |
| Product and catalog shape | Mission Control/CTF scenario selection uses the existing workflow-filtered catalog. CMS rechecks launchability and user/agent ownership; UI hiding alone is not admission. |
| Scenario parser/validator | Legacy YAML/DB data passes `cms.scenarios.schema` and hydration into canonical `RangeSpec`; ACES passes package identity/digest, compiler, manifest, plan, and feature checks. Scenario-owned data remains closed/bounded by its owner. |
| Persisted transport | Legacy intent is wrapped and canonically validated before `build_scenario_artifact` binds its digest; the provisioner verifies the closed range-cell request/digest. ACES validates producer/version/topology before realization. No raw JSON bag or `unwrap_persisted_spec` call is a trust gate. |
| Backend policy and ownership | `evaluate_gcp_backend_admission(..., LIVE_FIRE)` admits only GCE. Engine re-normalizes and writes the backend/purpose once; idempotent reuse rejects conflicts. Existing operations use the persisted binding, not a fresh env read. |
| Config/env shape | Root installation contract, runtime inventory, renderer, ConfigMap, Django/Engine forwarding, and `load_gce_range_cell_config` must agree. Profile JSON stays closed, duplicate-key rejecting, byte/entry bounded, and fully typed. New keys require every parity surface; unsupported config fails closed. |
| Privileged task admission | `validate_provisioner_command` and the launch-intent generation fence admit only canonical `range` / `aces-range` operations and UUIDs. GKE admission pins launcher identity, provisioner service account, digest-bound image, exact args/env, and runtime hardening. |
| OS/process exposure | Arguments carry only operation plus request/operation ids. Scenario artifacts, image maps, provider payloads, kubeconfigs, passwords, tokens, private keys, and secret references do not enter argv, shell strings, process titles, workflow output, or command logs. |
| Secret handling | `split_env` routes direct sensitive values to an ephemeral per-Job Secret with owner cleanup; GCP Secret Manager holds guest/access credentials. DB, events, cell results, and logs carry references only. Startup metadata must not become a general secret or scenario-payload transport. |
| Cloud identity and metadata | Provisioner Workload Identity performs control-plane mutation. Participant VMs have no external IP; attach only the minimum approved service account when the realizer proves it is needed. Shielded VM, metadata controls, OAuth scopes plus least-privilege IAM, and participant metadata blocking remain mandatory. |
| Network/DNS/egress | Allocated range subnets, per-range tags/firewalls, management-source separation, access-workload ingress, cross-range/platform/pod/service/node denial, DNS posture, and configured egress/PGA policy are outer invariants. Scenario topology cannot widen them. |
| State and cleanup | Request/generation ownership labels, persisted binding, canonical resource state, and allocation rows drive convergence. Cleanup proves ownership, distinguishes shared resources, is repeatable, and retains evidence on ambiguous failure. |
| Error envelopes and retries | Unsupported scenario capability and missing configuration use stable authored ADR-039 codes/messages. DRF uses `shared.api.errors`; CTF preserves code/details; durable events remain bounded notifications. Raw `str(exc)`, provider stderr, paths, CIDRs, resource lists, and secret refs do not cross user/event/websocket envelopes. Permanent denials are not retried. |
| Observability/audit | Existing audit events and request/range/operation correlation remain authoritative. Logs use sanitized scenario ids only when needed and otherwise counts/fingerprints; metrics use bounded backend/capability/code labels, never scenario ids or provider resource ids as unbounded dimensions. |

## Extensibility Seam

The required seam is the pair of:

- the existing realization-artifact discriminator/version plus immutable
  digest (`RangeSpec` artifact or ACES `ProvisioningPlan`); and
- the operation-scoped admitted substrate binding/capability.

The selected scenario realizer produces provider-safe membership and logical
access declarations for the existing cell lifecycle. The next scenario,
artifact version, internal orchestrator, or ACES cutover adds a realizer and
evidence at that seam, not a platform placement enum or scenario-name branch.

Bindings must remain cell-qualified rather than assuming one cell forever.
That preserves the issue's explicit allowance for one or more cells without
forcing a future multi-cell range to change CMS/CTF workflow, public lifecycle
status, or scenario-internal topology contracts.

## Whole-Repository Surfaces In Scope

Future implementation must evaluate all of these, even where no edit is needed:

- architecture/operator truth: ADR-030, ADR-039,
  `range-isolation-model.md`, `provider-neutral-range-substrate.md`,
  `scenario-gcp-range-cell-contract-preflight-1344.md`,
  `gdc-vm-runtime-live-fire-gate-preflight-1348.md`,
  `gcp-range-cell-deploy.md`, `polaris-gcp-range-cell.md`, GDC docs, and the GCP
  scenario support matrix;
- product entry points: Mission Control HTML/API, CTF event selection,
  participant/batch/retry, spares, replacement recovery, CMS legacy/ACES
  dispatch, and smoke/backend-validation management commands;
- catalog/contracts: YAML and DB legacy scenarios, Scenario Editor/registry,
  hydrator, persisted `RequestSpec`/`RangeSpec`, registered ACES packs and
  realizability;
- Engine: range creation, backend ownership binding, migrations/backfill,
  operation generation, launch intents/outbox/drainer, task env projection,
  status/event reconciliation, pause/resume/destroy, and access resolution;
- provisioner: config parsers, DB reads/writes, subnet allocation,
  `terraform_ops`, `terraform_vars`, `range_terraform_runner`,
  `gcp_range_cell_*`, ACES GCE realization, setup/bootstrap, state validation,
  compensation, errors/events/redaction, and retained GDC cleanup;
- deployment/runtime: `shifter/installation`, GCP runtime-env renderer and
  inventories, ConfigMap/Secret overlays, Helm and base Kubernetes manifests,
  both validating-admission-policy copies, RBAC/service accounts, Pod Security,
  provisioner image pinning, Terraform GCP range network/IAM, and Packer image
  promotion; and
- enforcement/evidence: CMS/CTF/Engine/provisioner tests, renderer/inventory and
  Job-admission parity tests, range escape probes, import-linter, ADR guard,
  action/Kubernetes/Terraform linters, and real-provider validation records.

## Gotchas And Anti-Patterns

- Do not equate `launchable`, `enabled`, an image mapping, a successful VM boot,
  or a green smoke scenario with complete GCP support.
- Do not branch on `scenario_id`, `role`, OS, `ami_key`, `asset_type`, or
  container count in the platform lifecycle. Compatibility interpretation stays
  in the owning realizer.
- Do not turn the support matrix into a second parser, manifest, registry, or
  authorization allowlist. It reports canonical validation and evidence.
- Do not import standalone provisioner modules into CMS to get an early answer,
  or copy GCE config/profile validation into Django. Cross-process feedback must
  use bounded canonical results; launch-time provisioner validation remains
  authoritative.
- Do not reread `GCP_RANGE_BACKEND` after a range has a persisted binding.
  Mixing bound routing with env-derived artifact validation, CIDR persistence,
  apply, or compensation can cross-wire GCE and GDC during a selector change.
- Do not classify a config or missing-image failure as permission to use GDC or
  a generic image. `prerequisite` and `unsupported-capability` fail closed.
- Do not add a GCP-specific Mission Control/CTF workflow, Engine repository,
  status enum, event family, exception hierarchy, access broker, subnet
  allocator, secret store, or task runner.
- Do not let a scenario supply provider project/zone, service-account email,
  firewall rule/tag, arbitrary startup metadata, secret reference, external IP,
  management CIDR, or provider API request.
- Do not attach the range-host service account to every participant VM. The
  existing Docker-host special case is compatibility debt, not a universal
  range-cell rule.
- Do not pass scenario/config JSON or credentials via argv or shell. Do not dump
  range-cell request/result, provider responses, Terraform output, guest output,
  or full exception strings to logs or failure events.
- Do not route a GCE compensation/destroy through GDC, and do not strand legacy
  GDC resources after a selector flip. Use persisted binding, durable ownership
  evidence, or the existing explicit operator backfill; ambiguity retains state
  and fails closed.
- Do not claim end-to-end acceptance from unit tests or a direct
  `gcp_range_cells.apply_range_cell` call. Validation must traverse the normal
  product/CMS/Engine/provisioner path, reach READY, verify declared access and
  isolation, and destroy cleanly.

## Non-Goals And Implementation Boundaries

- No implementation, formal Ground Control requirement, or implementation plan
  in this note.
- No universal range-host, standalone-VM, Windows/DC, container, nested
  Kubernetes, or placement taxonomy.
- No redesign of scenario content, CyberScript, ACES semantics, internal DNS,
  ports, topology, startup, bootstrap, or service discovery beyond the adapter
  needed to preserve authored behavior.
- No approval of GDC/GKE/Pods for normal live-fire ranges and no change to
  explicit non-user GDC validation/cleanup.
- No GCE NGFW implementation, new external-IP path, new access channel, or
  change to range escape criteria.
- No change to AWS selection, Terraform variables/state, IAM, setup, access, or
  cleanup behavior.
- No claim that catalog/config preflight proves real-provider operation. At
  least one enabled non-Polaris, product-shaped scenario must still be validated
  end to end through GCE with immutable evidence; synthetic smoke remains
  supporting evidence only.

## Live Validation Record

The first GCP development smoke attempt on 2026-07-27 traversed the normal
portal, CMS, Engine, durable outbox, and Kubernetes task-runner path for
`smoke_linux` (range 149, request
`650cae51-4db3-46ac-8160-7e0fdc95f918`) using the deployed portal image
`sha256:a85ea74003d43e8ada0c7c51fe04cc94dbe63e19992920f9db3a8af0b6d49664`.
The fail-closed `restrict-provisioner-jobs` policy rejected the provisioner Job
before provider execution because its command grammar had not been updated for
ADR-043's trailing `--operation-id <UUID>` correlation pair. No provisioner Job
was admitted and no GCE resource mutation occurred.

The resolution keeps the policy fail closed while accepting the canonical
request and legacy identifier forms both with and without the optional,
UUID-validated operation-generation suffix. The GCP base and Helm policy copies
remain identical, and rendered-CEL semantic tests cover accepted compatibility
forms plus malformed flag, UUID, operation, and arbitrary-suffix rejection.

After that policy correction, the backed-off destroy intent was admitted and
ran in the provisioner. It exposed a second pre-mutation recovery defect: the
deployed adapter tried to calculate an OpenVPN address from an empty CIDR even
though the failed provision had created no provider Job, CIDR allocation, or
GCE resource. The corrected destroy planner disables provision-only OpenVPN
requirements, retains deterministic resource identities, and tolerates absent
CIDR and gateway-pool bindings so idempotent deletion can converge after an
early failure. A regression test exercises that exact empty-binding,
OpenVPN-declared composition and still verifies Compute, Secret Manager, and
Vertex cleanup calls.

These failed attempts are diagnostic evidence only; they do not satisfy the
required successful provision, readiness, isolation, and teardown evidence.
The successful rerun is therefore a protected post-merge GCP development
deployment gate: the provenance-attested provisioner image must include this
change, then the operator must clean range 149 and run a fresh `smoke_linux`
range through READY, connectivity, and DESTROYED. Feature-branch image
deployment is not an accepted substitute for the protected provenance path.

## Required Future Evidence

- Mission Control, CTF participant, batch/retry, spare, replacement recovery,
  legacy, and ACES normal launches all admit only a GCE live-fire binding on GCP
  and never call GDC apply paths.
- Unsupported legacy shapes, NGFW, missing keyed/default images, domain mismatch,
  unsupported ACES terms, malformed artifacts, and invalid GCE config return
  stable fail-closed results before cloud mutation.
- Provision, compensation, pause/resume, destroy, and reconciliation use one
  persisted operation backend despite a deployment-selector change; AWS remains
  byte-for-byte on its existing routing behavior.
- Two materially different scenario compositions traverse the same cell
  boundary without lifecycle branches on scenario semantics. At least one is an
  enabled non-Polaris normal scenario validated through the full product path.
- Validation reaches READY only after scenario setup/access readiness and range
  escape checks, then proves repeatable teardown with no owned resources,
  secrets, state, or subnet allocation left behind.
- The operator matrix identifies supported, prerequisite-blocked, unsupported,
  and not-yet-validated scenarios with a stable safe reason and evidence date,
  without becoming runtime authorization.
