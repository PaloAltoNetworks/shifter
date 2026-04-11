# GDC/GCP Implementation Reconciliation

## Purpose

Reconcile the completed GCP slices against the post-spike architecture:

- `GKE` remains the control plane
- `GDC VM Runtime` becomes the default GCP range plane
- custom GDC L2 networks replace the old Compute Engine subnet model for scenario networking

This file classifies the existing implementation as:

- `keep`: valid as-is under the new architecture
- `retarget`: implementation is still useful, but its concrete GCP target must change
- `superseded`: active GCP path should stop building on this implementation

## Executive Summary

- The control-plane work remains valid.
- The provider seams remain valid.
- The GCP range-plane implementation from Slices 2 and 3 is not the right active path anymore because it assumes `Compute Engine VMs + Terraform-managed subnetworks` for range assets.
- The persistence, execution, bootstrap, and Guacamole work from Slices 4 through 7 should be kept, but retargeted to VM Runtime resources and custom GDC L2 networks.
- There are additional AWS-only runtime paths outside the original slice boundaries that must be updated before GDC can reach operational parity.

## Implemented Reconciliation Changes

These changes were applied immediately so the active code path matches the rewritten architecture instead of only documenting it.

### Active GCP range provisioning no longer silently uses the retired CE module

- [range_terraform_runner.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/range_terraform_runner.py) now treats the active GCP range path as GDC-only.
- The retired `terraform/modules/gcp-range` path has been removed from the repo instead of left selectable behind `GCP_RANGE_PLANE`.
- Default GCP state prefixes now resolve directly to `gcp/gdc-ranges`.

### Retired Compute Engine-only GCP inventory and tests are removed

- [cloud/gcp/network.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/cloud/gcp/network.py) no longer falls back to Compute Engine subnet inventory.
- GCP range inventory now requires the GDC access bundle and reads managed cluster `Network` objects only.
- The old Compute Engine range module tests and fixtures were deleted or rewritten to use GDC/VM Runtime-shaped metadata.

### GCP metadata extraction now accepts VM Runtime/GDC aliases

- [main.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/main.py) now folds `gcp_`, `gdc_`, and `vmruntime_` outputs into the nested `provider_metadata["gcp"]` block.
- This keeps the existing provider-aware persistence shape while making it usable for the future VM Runtime module outputs.

### Connection helpers now accept GDC-shaped asset metadata

- [services.py](/home/atomik/src/shifter-k8s/shifter/shifter_platform/engine/services.py) now resolves:
  - `provider_metadata.gdc`
  - host aliases like `ip`, `guest_ip`, `vm_ip`
  - SSH key aliases like `ssh_secret_ref`, `ssh_secret_id`
  - VM naming aliases like `vm_name`
  - username alias `username`
- The Windows RDP/SFTP helper now uses the same provider-aware SSH secret resolution path instead of relying only on the legacy `ssh_key_secret_arn` field.

### AWS-only lifecycle code now fails fast for non-AWS ranges

- [range_ops.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/range_ops.py) now raises `NotImplementedError` for non-AWS ranges instead of pretending the EC2 pause/resume path can operate on future GDC assets.
- This is intentional guardrail behavior until the later GDC lifecycle slice lands.

## Slice Reconciliation

### Slice 1: GCP range network foundation and provider-routed range network contract

Status: `keep with minor retargeting`

Why:
- The provider-neutral contract in [config.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/config.py) is still the right abstraction boundary.
- The idea of `RANGE_NETWORK_*` plus `PORTAL_NETWORK_CIDRS` survives the architecture change.

What changes:
- `RANGE_NETWORK_ID` should stop meaning "Compute Engine VPC/subnetwork target for Terraform guest instances" and start meaning the GDC range-plane network context.
- Slice 10 should extend this contract with VM Runtime and custom L2 network fields instead of replacing it.

Primary files:
- [config.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/config.py)

### Slice 2: GCP range Terraform module

Status: `superseded for the active GCP range path`

Why:
- The module under [main.tf](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/terraform/modules/gcp-range/main.tf) creates:
  - `google_compute_subnetwork`
  - `google_compute_firewall`
  - `google_compute_instance`
  - Secret Manager SSH keys for those instances
- That is the old `Compute Engine range VM` model, not the new `GDC VM Runtime + custom L2 network` model.

What survives:
- image/bootstrap variable patterns may still be reusable later
- output naming conventions for instance metadata can inform the VM Runtime equivalent

What changes:
- The active GCP range module should no longer create range Compute Engine subnetworks and range Compute Engine guest instances.
- Slice 10/11 should introduce a GDC-native implementation for:
  - custom `Network`
  - `NetworkAttachmentDefinition`
  - VM Runtime disks / VMs

Primary files:
- retired module removed from `shifter/engine/provisioner/terraform/modules/gcp-range/`

### Slice 3: provider-routed range runner and GCP state backend routing

Status: `retarget`

Why:
- Provider-routed state and backend selection are still correct.
- The GCS backend path in [terraform_base.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/terraform_base.py) remains valid.

What changed:
- [range_terraform_runner.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/range_terraform_runner.py) no longer exposes the superseded `gcp-range` module.
- The active GCP range-plane runner now targets the GDC network runner only.
- State-key naming now uses `gcp/gdc-ranges`.

Primary files:
- [range_terraform_runner.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/range_terraform_runner.py)
- [terraform_base.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/terraform_base.py)

### Slice 4: provider-aware range metadata persistence

Status: `retarget`

Why:
- The generic `cloud_provider` plus `provider_metadata` pattern in [main.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/main.py) is still correct.
- The Django-side connection resolution in [services.py](/home/atomik/src/shifter-k8s/shifter/shifter_platform/engine/services.py) is already flexible enough to consume provider-specific metadata.

What changes:
- The current GCP payload shape is still Compute Engine shaped:
  - `gcp_subnetwork_id`
  - `gcp_instance_id`
  - `gcp_zone`
  - `gcp_private_ip`
- The active GCP payload should evolve toward VM Runtime and GDC network artifacts:
  - network name / namespace / NAD
  - VM Runtime VM name / namespace / disk refs
  - interface names and custom L2 IP assignments

Primary files:
- [main.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/main.py)
- [services.py](/home/atomik/src/shifter-k8s/shifter/shifter_platform/engine/services.py)

### Slice 5: GCP remote execution backend

Status: `retarget`

Why:
- The split between provider-routed execution contexts in [factory.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/executors/factory.py) is still the right abstraction.
- Direct SSH into guests is still likely the correct baseline execution path for VM Runtime guests.

What changes:
- The GCP branch currently assumes the target comes from the old CE outputs:
  - `private_ip`
  - `ssh_key_secret_arn`
- The VM Runtime path needs the same executor abstraction fed by VM Runtime asset metadata instead of CE instance outputs.
- Windows SSH assumptions need to be revalidated against the chosen VM Runtime guest images.

Primary files:
- [factory.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/executors/factory.py)
- [guest_ssh_executor.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/executors/guest_ssh_executor.py)

### Slice 6: bootstrap/domain/XDR parity groundwork

Status: `retarget`

Why:
- The setup orchestration logic is still valuable.
- The policy decision to prefer runtime DC promotion on GCP can still stand if it proves correct for VM Runtime guest images.

What changes:
- The current GCP assumptions are still tied to the superseded CE startup-template path.
- VM Runtime image import, startup handling, and guest readiness behavior must become the new source of truth.
- Slice 13 should explicitly reconcile the existing GCP setup-plan assumptions with VM Runtime disk / image lifecycle.

Primary files:
- [main.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/main.py)
- DC/XDR plan files under [plans](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/plans)

### Slice 7: Guacamole connectivity groundwork for GCP guest assets

Status: `retarget`

Why:
- The Guacamole SSH/RDP integration work remains useful.
- The platform-side host resolution in [services.py](/home/atomik/src/shifter-k8s/shifter/shifter_platform/engine/services.py) is already metadata-driven enough to be reused.

What changes:
- The GCP asset target should become VM Runtime assets first, not CE instances.
- Any assumptions that the asset name, IP, or key reference come from the old CE module outputs need to shift to VM Runtime metadata.

Primary files:
- [services.py](/home/atomik/src/shifter-k8s/shifter/shifter_platform/engine/services.py)
- [views.py](/home/atomik/src/shifter-k8s/shifter/shifter_platform/mission_control/views.py)
- [guacamole.py](/home/atomik/src/shifter-k8s/shifter/shifter_platform/mission_control/guacamole.py)

## Additional Runtime Gaps Found Outside the Original Slices

These are not new regressions from the architecture rewrite; they were simply outside the earlier slice scope. They now matter because they would block a real GDC range plane later.

### Range pause/resume is still AWS-only

Status: `retarget`

Evidence:
- [range_ops.py](/home/atomik/src/shifter-k8s/shifter/engine/provisioner/range_ops.py) still speaks entirely in `aws_instance_id` and EC2 semantics.

Impact:
- Even after VM Runtime asset lifecycle exists, pause/resume/destroy parity will remain incomplete unless this code is rewritten around provider-aware operations.

### NGFW lifecycle is still AWS-shaped

Status: `partially retargeted`

Evidence:
- The current NGFW lifecycle still uses AWS runtime start/stop operations for actual instance power state changes.
- Slice 14 moved the attachment and access contract to provider-neutral state:
  - NGFW lookup no longer hardcodes `data_eni_id`
  - range binding now persists explicit `attached_ranges`
  - NGFW terminal access now resolves provider metadata
  - non-AWS NGFW runtime ops fail fast instead of attempting EC2 actions

Impact:
- The remaining gap is no longer the attach/detach contract.
- The remaining gap is the real non-AWS NGFW runtime/provisioning path for GCP/GDC.

## Concrete Follow-Up Map

### Keep Building On Directly

- provider-neutral range network config and env contract
- provider-neutral state metadata pattern
- provider-routed executor abstraction
- Django-side connection metadata resolution
- GDC bootstrap command and owned admin-cluster bring-up

### Stop Extending On the Active GCP Path

- any new GCP range logic that assumes Compute Engine range subnet / guest provisioning
- any code that treats the active GCP module path as `terraform/modules/gcp-range`

### Next Slices Should Do This

1. Slice 12
   Rebind the current persistence and connection abstractions to mixed VM Runtime VM + scenario Pod assets.

2. Slice 13
   Reuse the current bootstrap/Guacamole groundwork, but feed it from VM Runtime asset metadata instead of CE outputs.

3. Slice 15
   Rewrite pause/resume parity and non-AWS NGFW runtime control off the current AWS-only `range_ops.py` / EC2 path.

## Recommended Implementation Rule From Here

For all future GCP range-plane changes:

- `keep` the abstraction if it is still provider-neutral
- `retarget` the implementation if it assumes GCP means Compute Engine range assets
- `do not` reintroduce a second GCP range plane unless there is a deliberate new architecture decision
