# GCP Range-Cell Backend Preflight

Issue: GitHub #1341, "Implement GCP range-cell provisioning backend."

This is requirement-free pre-implementation guidance. The GitHub issue title,
body, and acceptance criteria are the shipping contract. This note is not an
implementation plan.

## Decision Boundary

The new backend must add a GCP Compute Engine range-cell substrate below the
existing range lifecycle contract. It is not a new CMS product workflow, a new
CTF lifecycle, a new public scenario schema, or a Kubernetes participant
runtime.

Keep the management plane and participant plane separate:

- GKE/Kubernetes runs Shifter management workloads and provisioner Jobs only.
- Participant-executable workloads run inside range VMs in the range network,
  including Docker/Compose-backed Linux scenario assets.
- GDC VM Runtime remains a different GCP substrate. Do not overload GDC
  resource names, metadata keys, or lifecycle assumptions for Compute Engine.

The implementation has an upstream architecture dependency: the ADR selected by
#1340 must be present locally and treated as the source of truth for the range
network-cell model before the backend lands. This note does not select that
model. If #1340 changes the platform/range network posture, update
`docs/adr/index.yaml`, related architecture docs, and enforcement evidence in
the same change.

## Architecture Decisions And Guardrails

- Preserve the existing CMS -> Engine -> provisioner boundary. CMS owns user
  intent, ownership, and CTF/Mission Control lifecycle semantics; Engine owns
  durable request/range state and task dispatch; the provisioner owns GCP
  resource mutation and cleanup.
- Use `request_id` as the cross-boundary correlation key. Do not add a parallel
  workflow/job/operation identity that leaks into CMS, CTF, Mission Control, or
  event payloads.
- Keep public status on `Range.Status` / `ResourceStatus`. Backend-specific
  phase, retry, and cleanup detail belongs in operation/provider metadata, not
  in a competing public status enum.
- Persist enough provider state to destroy without re-deriving names from live
  cloud inventory: network/subnet, route/firewall, VM, disk, address, service
  account/tag, and secret-reference identifiers, plus zone/region/project and
  ownership labels.
- Add one explicit GCP range-substrate/profile selector below
  `CLOUD_PROVIDER=gcp`, owned by the backend bundle/runtime-env path and the
  #1340 ADR. It should route between the current GDC range plane and the new
  Compute Engine range-cell backend without creating a second cloud-provider
  selector.
- Treat deterministic IP assignment as part of the provider-internal range
  plan/state contract. Assign IPs from allocated cell CIDRs before VM creation
  and persist them through the existing state writers so portal, Guacamole,
  setup, and teardown do not recompute them differently.
- Keep destroy idempotent and complete. Missing resources, repeated destroy,
  and partial-create failure cleanup must converge to destroyed state while
  preserving operator-visible errors for resources that cannot be removed.

## Cross-Cutting Concerns To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| User workflow and ownership | `cms.services._range_create`, `_range_destroy`, `_range_pause`, `_range_resume`, Mission Control range APIs, CTF range bridges | Do not authorize or lifecycle ranges from GCP-specific code paths. Preserve existing CMS/CTF semantics. |
| Request/spec schemas | `shared.schemas.RequestSpec`, `RangeSpec`, persisted spec envelope helpers | Do not add duplicate DTOs or validators for range cells. Add provider metadata only where the public contract is unchanged. |
| Engine lifecycle | `engine.services._range`, `engine.ecs`, `Range.status`, `provisioning_task_arn`, `teardown_task_arn` | Dispatch the same `["range", operation, "--request-id", ...]` command family and keep task identifiers on existing fields. |
| Provisioner range boundary | `terraform_ops.run_range_terraform`, `range_terraform_runner.apply_range/destroy_range`, `terraform_vars._build_range_terraform_variables` | Route the new backend under the existing provisioner lifecycle entrypoint. Rename only if the whole call chain is cleaned consistently; do not create a parallel range runner stack. |
| Subnet/CIDR allocation | `components.network.allocate_subnets`, `release_subnet_allocations`, `SubnetAllocation`, `cloud.gcp.network.GCPNetworkInventory` | Reuse the DB-serialized allocation table and provider inventory seam. Extend GCP inventory for Compute Engine subnets instead of bypassing allocation. |
| State persistence | `provisioner_db.write_provisioned_state`, `mark_range_instances_destroyed`, `state_helpers._validate_provisioned_outputs`, `_build_subnet_state`, `_build_instance_state`, `_build_provisioned_instance_payload` | Store top-level compatibility fields plus `cloud_provider: "gcp"` and nested `provider_metadata.gcp`. |
| Runtime env binding | `scripts/gcp/render_runtime_env.py`, `config/env-manifest.json`, `shifter/installation/runtime_inventory.py`, `engine/ecs.py` `_GCP_PROVISIONER_ENV_KEYS` | New runtime knobs must flow through the generated env/inventory path and task-runner env allowlist. |
| Secrets | `cloud.get_secrets_store`, `shared.cloud.sensitive_env`, `engine.secrets`, provisioner `log_redact` | Store only secret references in DB/provider metadata. SSH keys, Windows/RDP passwords, service-account keys, and setup credentials must not go into metadata, startup scripts, logs, events, or argv. |
| Events and reconciliation | `events.publish_*`, `engine_range_event_outbox`, `reconcile_range_events` | Events stay notification-shaped and replayable. DB state remains authoritative. |
| Errors and logging | `shared.errors`, `shared.api.errors`, `shared.log_sanitize`, provisioner `log_redact.safe_log_fingerprint` | User-facing errors get fixed/sanitized messages; logs carry request IDs, counts, phases, and fingerprints, not raw provider payloads. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: Mission Control and CTF must enter through existing CMS service
  functions and permission checks. No GCP backend code may become an ownership
  oracle by querying Engine rows directly from views or API serializers.
- Input shape checks: request data must pass `RequestSpec` / `RangeSpec`,
  persisted envelope validation, CMS validators, and provisioner output
  validation before DB writes. Provider plan rendering should be an internal
  typed shape, not a new public scenario DSL.
- Config validators: backend selector, project, region, zone, image, machine
  type, network, egress mode, firewall ports, and service-account/tag strategy
  must be validated through installation/runtime inventory, Terraform variable
  validation where stable infrastructure changes, and focused provisioner tests.
- GCP VPC policy: range ingress remains explicit and least privilege per
  ADR-008-R4 and `docs/architecture/gcp-vpc-firewall-preflight.md`. No public
  SSH/RDP, no reliance on default firewall rules, and no broad "allow internal"
  rule across peered VPCs.
- Metadata/API hardening: Compute Engine VMs must not use the project default
  service account or project-wide SSH keys. Require minimal service accounts,
  intentional network tags/service accounts for firewall targeting, disabled
  legacy metadata endpoints, blocked project SSH keys, and no secret values in
  startup metadata.
- OS/process exposure: prefer Google SDK calls for GCP mutation. Any external
  CLI fallback must use argv arrays, temporary files with cleanup, and no
  shell strings carrying credentials, kubeconfigs, JSON keys, startup scripts,
  or secret payloads.
- Secret boundary: per-instance SSH/RDP credentials and optional Windows/DC
  material are generated or fetched by the provisioner and stored in Secret
  Manager by reference. GCE metadata, Terraform output, DB JSON, events,
  Channels payloads, and user-facing errors carry references or sanitized
  availability state only.
- Error envelopes: provider SDK errors, operation IDs, full resource names,
  metadata server responses, startup-script output, and cleanup failures must
  be mapped to bounded provisioner logs and sanitized CMS/API messages.
- Event/outbox layer: successful state transitions must enqueue or publish
  through the existing range event path. Event loss must be recoverable from DB
  state; event payloads must not contain provider resource inventories.

## Extensibility Seam

The seam is a request-scoped GCP range-cell backend profile:

- provider: `gcp`
- substrate/profile: current GDC VM Runtime or new Compute Engine range cell
- network-cell model: the #1340 ADR-selected model
- placement: region plus zone or ordered zone policy
- image/profile map: Linux range host and optional Windows/DC VM profile
- IP plan: deterministic subnet and per-VM address assignment
- cleanup policy: per-range vs shared service accounts, tags, addresses, and
  disks
- egress posture: existing range-egress policy bridge

That parameterization leaves room for `gcp-prod`, alternate VM images, multiple
zones, Windows/DC-only scenarios, future NGFW attachment, and different
per-range network-cell shapes without re-editing CMS, CTF, Mission Control, or
the public `RangeSpec` contract.

## Whole-Repo Surfaces In Scope

Likely implementation surfaces:

- #1340 ADR / architecture note and `docs/adr/index.yaml` if the selected model
  changes guardrails.
- `docs/adr/documentation-coverage.yaml` plus one user doc and one technical
  doc when the feature ships, per ADR-022.
- `shifter/installation/**`, `scripts/gcp/render_runtime_env.py`,
  `scripts/bootstrap/deploy.py`, `config/env-manifest.json`, and
  `engine/ecs.py` for new runtime env or backend-bundle knobs.
- `platform/terraform/gcp/modules/range/vpc/**` and `platform-core` outputs if
  stable range-network or firewall contracts change.
- `shifter/engine/provisioner/config.py`, `cloud/gcp/**`,
  `components/network.py`, `range_terraform_runner.py`, `terraform_ops.py`,
  `terraform_vars.py`, `provisioner_db.py`, and `state_helpers.py`.
- Tests under `shifter/engine/provisioner/tests/**`,
  `shifter/shifter_platform/tests/engine/ecs/**`,
  `shifter/shifter_platform/tests/shared/cloud/**`, `scripts/gcp/tests/**`,
  and Terraform/Kubernetes manifest tests matching touched surfaces.

## Gotchas And Anti-Patterns

- Do not run participant containers as Kubernetes pods or attach them to the
  platform pod network. Docker/Compose belongs inside the Linux range host VM.
- Do not silently replace the current GDC path just because
  `CLOUD_PROVIDER=gcp` is already routed there. The new Compute Engine backend
  needs an explicit substrate/profile gate.
- Do not copy GDC metadata names (`gdc_namespace`, `gdc_nad_name`,
  `vmruntime_disk_name`) for Compute Engine resources. Use GCP provider
  metadata that names the actual resource kind.
- Do not rely on naming conventions alone for cleanup. Persist provider
  operation/resource IDs and use labels as a secondary reconciliation aid.
- Do not leave disks, static addresses, firewall rules, service accounts, or
  tags orphaned when create fails after a partial resource set.
- Do not delete shared service accounts, shared firewall rules, or stable VPC
  objects from per-range destroy. Shared vs per-range ownership must be explicit
  in state.
- Do not put SSH private keys, RDP/Windows passwords, domain admin material,
  service-account JSON, API tokens, or full startup scripts into process argv,
  GCE metadata, Terraform outputs, events, test snapshots, or logs.
- Do not treat a missing firewall endpoint, empty allowlist, or absent NAT path
  as an implicit zero-egress mode. Use the existing range-egress contract.
- Do not hardcode project IDs, zones, image families, CIDRs, machine types, or
  service-account names in provisioner code.
- Do not widen GCP IAM or Workload Identity grants to compensate for backend
  gaps. Provisioner permissions should be narrowly scoped to the resources it
  must create, inspect, and destroy.
- Do not add a new exception hierarchy or raw provider error envelope for this
  backend. Reuse the existing cloud/provisioner exception and sanitized user
  message patterns.

## Non-Goals And Boundaries

- No implementation in this preflight note.
- No new formal Ground Control requirement.
- No selection of the #1340 range network-cell model here.
- No replacement of CMS/CTF range lifecycle semantics, public status values,
  `RangeSpec`, task runner, event bus, Secret Manager abstraction, or
  reconciliation model.
- No redesign of GDC VM Runtime, VM-Series NGFW, Identity Platform, Cloud
  Armor, GKE deployment, Kubernetes Job admission, or AWS range provisioning.
- No pause/resume parity unless the issue scope is explicitly expanded; until
  supported, lifecycle operations should fail closed with sanitized messages
  rather than pretending Compute Engine state is equivalent to AWS or GDC.

## Validation Surface

Any implementation touching architecture, workflows, hooks, Terraform, or
`shifter/shifter_platform` must run the repo-required checks for the touched
surfaces:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
actionlint
kube-linter lint --config .kube-linter.yaml platform/k8s/
kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.31.0 platform/k8s/gcp/base/*.yaml
```

Focused tests must cover provisioning plan rendering, idempotent create,
partial-failure cleanup, repeated destroy, persisted state shape, deterministic
IP assignment, secret-reference handling, and no participant workload placement
on Kubernetes/GKE pod networks.
