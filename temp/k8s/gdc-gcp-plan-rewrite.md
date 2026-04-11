# GCP/GDC Execution Plan Rewrite

## Why This Rewrite Exists

The original GCP plan assumed:

- GKE for the control plane
- Compute Engine for range VMs
- pods only for non-kernel assets

That is no longer the right default model for the GCP range plane.

The live Google Distributed Cloud spike in `prod-rwctxzl6shxk` proved:

- the default `pod-network` is not the flat mixed-subnet model needed for scenario networking
- a custom GDC `Network` attached to the cluster's `vxlan0` fabric can host both:
  - VM Runtime VMs
  - normal Pods attached with `NetworkAttachmentDefinition`
- those mixed assets can communicate on the same custom subnet across nodes

So the remaining plan needs to pivot from:

- `Compute Engine range plane with optional KubeVirt later`

to:

- `GKE control plane + GDC VM Runtime range plane + custom L2 scenario networks`

## Preserved Progress

The completed work from the original plan is still useful and remains preserved:

1. Slice 1: GCP range network foundation and provider-routed range network contract
2. Slice 2: GCP range Terraform module
3. Slice 3: Provider-routed range runner and GCP state backend routing
4. Slice 4: Provider-aware range metadata persistence
5. Slice 5: GCP remote execution backend
6. Slice 6: Bootstrap/domain/XDR parity groundwork
7. Slice 7: Guacamole connectivity groundwork for GCP guest assets

What changes is the target shape of the **range plane**. The control-plane and abstraction work already done still matters.

Implementation reconciliation note:

- a code-level follow-up review now lives in `temp/k8s/gdc-gcp-implementation-reconciliation.md`
- that review classifies the old slices as `keep`, `retarget`, or `superseded`
- the biggest active-path change is that the old Compute Engine `gcp-range` module is no longer the right foundation for future GCP range-plane work
- the initial reconciliation code changes are already applied:
  - the retired Compute Engine `gcp-range` module has been removed
  - default GCP range routing is now GDC-only
  - GCP subnet inventory no longer falls back to Compute Engine APIs
  - provider metadata extraction now accepts `gdc_` and `vmruntime_` aliases
  - Django-side connection helpers now accept GDC-shaped asset metadata
  - AWS-only pause/resume now fails fast for non-AWS ranges

## Revised Architecture Rules

### Control Plane

- Keep `gcp-dev` control-plane workloads on Kubernetes.
- The current GKE/GCP control-plane work remains valid for:
  - portal
  - workers
  - Guacamole
  - async jobs
  - platform services

### Range Plane

- The GCP range plane should target **Google Distributed Cloud VM Runtime**.
- The default scenario segment model should be a **custom GDC L2 network**, not `pod-network`.
- Scenario endpoints can be:
  - VM Runtime VMs
  - normal Pods on the same custom subnet when lower fidelity is acceptable

### Fidelity Rule

- VM Runtime VMs are the default when host fidelity matters.
- Normal Pods are allowed in-range only when it is acceptable that an attacker may fingerprint them as container-backed workloads.
- High-fidelity scenarios are therefore a placement decision, not a platform limitation.

### Networking Rule

- Do not use default `pod-network` for attacker-visible flat-subnet scenarios.
- Use GDC `Network` + `NetworkAttachmentDefinition` for custom shared scenario subnets.
- Treat the cluster's `vxlan0` fabric as the evaluation/prototype underlay unless and until production networking specifies a different underlay.

### Operational Rule

- Fix real control-plane/runtime issues as part of the platform work instead of routing around them.
- The inotify/macvtap failure is now a known bootstrap hardening requirement, not a one-off spike workaround.

## Rewritten Remaining Slices

### Slice 8: Codify the New Range-Plane Architecture

Goal:
- Replace the old "Compute Engine range plane" assumption with a repo-tracked GDC VM Runtime architecture.

Deliverables:
- update the active execution tracker to make GDC VM Runtime the default GCP range-plane target
- write the architecture decision into repo-local planning notes under `temp/k8s/`
- identify which existing GCP range components are still reusable vs superseded
- define the placement rule for:
  - VM Runtime VM assets
  - pod-backed in-range assets
  - control-plane assets

Exit criteria:
- there is one clear written model for GCP ranges and it no longer contradicts the validated spike result

### Slice 9: Bootstrap and Harden a Repeatable GDC Cluster Path

Goal:
- make the GDC VM Runtime testbed reproducible from repo automation instead of manual shell history

Status:
- implemented in `scripts/bootstrap/deploy.py` as the `gdc-bootstrap` command
- validated locally with bootstrap unit tests, lint, ADR fast checks, and shell-parse checks for the rendered remote scripts

Deliverables:
- integrate GDC bootstrap into `scripts/bootstrap/deploy.py` or the correct bootstrap owner path
- provision the required GCP substrate for the GDC-on-Compute-Engine path
- enable required APIs and IAM bindings
- create the cluster VPC/subnet and host VMs
- create the GDC cluster
- enable VM Runtime
- bake in the inotify sysctl fix before VM Runtime workloads are enabled
- ensure the admin access path and kubeconfig ownership model are sane for repeatable use

Exit criteria:
- a clean project can be brought to a working VM Runtime-capable cluster through owned bootstrap code

### Slice 10: Scenario Network Provisioning on GDC Custom L2 Networks

Goal:
- turn the spike network pattern into provisioner-owned range networking

Status:
- implemented in the provider-routed GCP range path, with the following owned pieces:
  - bootstrap sync of a `shifter-gcp-dev-gdc-access` Secret Manager bundle
  - provisioner-owned GDC `Network` and `NetworkAttachmentDefinition` create/destroy logic
  - provider metadata persistence for GDC subnet resources
  - GDC-aware network inventory for subnet allocation reconciliation
  - GKE Job env forwarding for the new GDC access/network settings
- full GCP range readiness is still intentionally blocked until Slice 11 lands, because VM Runtime guest lifecycle is not wired yet

Deliverables:
- model a scenario segment as a GDC custom `Network`
- generate paired `NetworkAttachmentDefinition` objects for pod attachment
- implement IPAM pool rules, including reserved gateway/static exclusions
- provision per-range or per-segment L2 networks through the provisioner
- store provider metadata for network names, addresses, pool ranges, and reserved IPs

Exit criteria:
- the platform can create and destroy shared L2 scenario networks in GDC without hand-written manifests

### Slice 11: VM Runtime Asset Lifecycle in the Provisioner

Goal:
- move GCP in-range compute from Compute Engine assumptions to VM Runtime-managed assets

Status:
- implemented in the active GCP range path
- GCP ranges now create and destroy `VirtualMachineDisk` and `VirtualMachine` resources through the provisioner
- bootstrap now syncs a Secret Manager secret for GCS-backed VM image imports
- the provisioner owns deterministic per-instance SSH secrets and persists VM Runtime metadata into range state
- GDC custom-resource reconciliation now uses patch semantics instead of brittle full-object replace calls

Deliverables:
- create VirtualMachineDisk and VirtualMachine resources from the provisioner
- support Linux and Windows VM images
- handle storage/import lifecycle and placement constraints
- attach VM interfaces to custom scenario networks
- persist VM Runtime-specific metadata in range state
- clean up VM disks and VM resources on destroy

Exit criteria:
- the provisioner can create, track, and destroy VM Runtime VMs as first-class range assets

### Slice 12: Mixed-Asset Range Composition

Goal:
- support both VM-backed and pod-backed in-range assets on the same scenario subnet

Status:
- implemented in the active GCP range path
- range specs and hydrated CMS context now distinguish:
  - `vm_runtime_vm`
  - `scenario_pod`
- the provisioner now creates mixed GDC ranges by:
  - assigning deterministic per-asset IPs across a shared subnet
  - creating VM Runtime VMs for `vm_runtime_vm` assets
  - creating Multus-attached scenario Pods for `scenario_pod` assets
- setup/bootstrap is intentionally skipped for pod-backed assets
- Django-side connection helpers now reject SSH/RDP requests for pod-backed assets explicitly instead of assuming every scenario asset is VM-like

Deliverables:
- add an asset-type contract that distinguishes:
  - `vm_runtime_vm`
  - `scenario_pod`
- attach scenario Pods to the same custom L2 network as VM assets
- preserve provider metadata so access/connectivity code can treat both as scenario assets
- prove a range definition can contain a VM asset and a pod asset on one subnet with deterministic IP assignment

Exit criteria:
- a single range can intentionally mix Pod and VM Runtime assets on the same subnet

### Slice 13: Bootstrap, Guest Access, and Tooling for VM Runtime Assets

Goal:
- make VM Runtime assets usable for real scenarios

Status:
- implemented in the active GCP path
- VM Runtime guest user-data now installs or enables the access tooling the platform expects:
  - OpenSSH
  - xrdp on Linux desktop guests
  - RDP and SSH firewall/service enablement on Windows guests
- the guest bootstrap path now sets explicit GDC runtime credentials for:
  - Kali desktop access
  - Ubuntu desktop access
  - Windows Administrator access
  - Domain Controller access via `DC_DOMAIN_PASSWORD`
- GKE provisioner Jobs now receive the same guest credential env contract as the control plane
- Django-side RDP helpers now resolve GCP VM Runtime credentials from the same env contract instead of using stale AWS-era defaults
- targeted provisioner and Django access tests now cover the VM Runtime credential/bootstrap path
- live end-to-end validation against the rebuilt GDC cluster is still outstanding; this slice is implemented and locally validated

Deliverables:
- Linux and Windows bootstrap for VM Runtime guests
- startup/cloud-init handling that works with the chosen guest images
- domain controller and domain-join flow on VM Runtime
- XDR/XSIAM install path on VM Runtime Windows and Linux assets
- Guacamole/SSH/RDP integration against VM Runtime assets

Exit criteria:
- real scenario guest types can be bootstrapped and accessed through the platform on GDC

### Slice 14: VM-Series / NGFW Integration Against GDC Scenario Networks

Goal:
- preserve independent firewall lifecycle management in the new GCP architecture

Status:
- implemented in the active GCP path as a provider-neutral NGFW attachment contract
- range provisioning no longer assumes `data_eni_id` is the only valid NGFW routing primitive
- NGFW lookups, range binding, and terminal access now resolve provider-neutral state:
  - management IP
  - SSH secret reference
  - dataplane / next-hop routing IP
  - attachment mode
- GCP/GDC ranges now persist explicit attach/detach state back onto the NGFW instance via `attached_ranges`
- range provisioning no longer falls into AWS EC2 start/stop logic for non-AWS NGFWs
- the PAN-OS subnet configuration plan now accepts a generic next-hop IP instead of an AWS-only VPC gateway parameter
- AWS NGFW Terraform state now writes the provider-neutral attachment metadata so the new contract is populated on the existing path
- concrete GCP NGFW provisioning/runtime control now targets Palo Alto VM-Series on GDC VM Runtime
- the GDC path is not a generic firewall implementation:
  - it creates Palo Alto VM-Series VM Runtime resources
  - it creates per-instance VM-Series bootstrap ISO media in GCS
  - it models management/data VM-Series interfaces explicitly
  - it persists `palo-alto-vm-series` product metadata for range attachment and terminal access
  - GCP NGFW start/stop now routes through the GDC VM-Series runtime operation path

Deliverables:
- define how Palo Alto VM-Series integrates with GDC scenario networks
- preserve independent VM-Series lifecycle management from ephemeral range assets
- implement attach/detach semantics between ranges and VM-Series firewalls
- route or bridge scenario networks through the Palo Alto VM-Series design as required by the scenario model

Exit criteria:
- GCP retains the current product capability of independently managed Palo Alto firewall lifecycle while using GDC for the range plane

### Slice 15: Operational Parity and Hardening

Goal:
- close the platform gaps after the GDC range plane exists

Deliverables:
- pause/resume/destroy parity for GDC assets
- observability for GDC cluster, VM Runtime, and range networking
- cleanup/garbage-collection for orphaned VM disks and custom networks
- OIDC and access hardening for the platform side
- cost controls and placement guardrails for pod vs VM asset choices

Exit criteria:
- `gcp-dev` is operationally supportable, not just technically functional

## Recommended Next Slice

Start with **Slice 15**.

Reason:
- the active GCP path now has:
  - GDC bootstrap
  - custom L2 scenario networks
  - VM Runtime guest lifecycle
  - mixed VM + Pod range composition
  - guest bootstrap/access credential integration
  - provider-neutral NGFW attachment and access state
- the next major capability gap is operational parity and hardening:
  - GDC pause/resume lifecycle
  - orphan cleanup
  - observability
  - platform-side hardening

The current implementation already captured the key earlier lessons:

- custom VPC/subnet creation is required in empty projects
- the GDC-on-Compute-Engine path needs explicit substrate creation
- VM Runtime enablement needs to be part of cluster bring-up
- the inotify/macvtap fix should be baked into bootstrap
