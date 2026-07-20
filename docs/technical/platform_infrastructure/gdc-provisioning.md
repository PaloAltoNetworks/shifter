# GDC Range Provisioning

Range guest provisioning on Google Distributed Cloud (GDC). GDC uses KubeVirt for VM workloads and Kubernetes-native networking for guest isolation.

On AWS, ranges are EC2 instances in isolated VPC subnets. On GDC, ranges can be KubeVirt VMs or lightweight pods on a GDC cluster, connected via custom L2 networks.

> **Status: development / validation only, not approved for live-fire (ADR-030).**
> The GDC VM Runtime backend, its scenario Pods, and its L2 Networks are **not** an
> approved containment boundary for live-fire ranges (participants and agents that
> run arbitrary activity). The supported GCP live-fire backend is **GCE VM range
> cells** (`GCP_RANGE_BACKEND=gce`, the default). Normal Mission Control and CTF
> range provisioning **fails closed** on GDC: the CMS service boundary rejects a
> live-fire launch whenever `GCP_RANGE_BACKEND=gdc`, and the provisioner
> independently denies a live-fire GDC apply as defense in depth (issue #1348).
> GDC provisioning documented here is for operator/development validation of GDC
> scaling and admission behavior only; that evidence is **not** live-fire
> containment evidence. A future explicit non-user validation entry point is
> tracked by #1354.

## Runtime Primitives

The provisioner supports three GDC runtime primitives:

| Type | Module | What It Creates | Use Case |
|------|--------|----------------|----------|
| **VM Runtime** | `gdc_vmruntime_assets.py` | `VirtualMachine` + `VirtualMachineDisk` CRDs | Full OS guests (Kali, Ubuntu, Windows, Domain Controller) |
| **Scenario Pods** | `gdc_scenario_pods.py` | Kubernetes Pods with network attachments | Lower-fidelity container execution where full guest semantics are not required |
| **VM-Series NGFW** | `gdc_vmseries_ngfw.py` | VM-Series firewall VMs on GDC VM Runtime | Palo Alto Networks NGFW integration |

Current direction:

- live-fire GCP ranges (Mission Control, CTF) run on **GCE VM range cells**, not
  on the GDC VM Runtime path; see the status note above and ADR-030
- the GDC VM Runtime path is retained for operator/development validation of GDC
  scaling and admission behavior only
- pod execution is an internal optimization/runtime mode, not an author-facing scenario contract
- mixed ranges are valid when the provisioner determines different runtimes are appropriate for different guests on the same L2 network

## Network Provisioning

Module: `gdc_range_networks.py`

Each range gets isolated L2 networking:

1. **Network CR** - GDC `Network` custom resource defining the L2 segment (VXLAN-based)
2. **Network Attachment Definition** - CNI NAD for multi-NIC pod/VM attachment
3. **Subnet allocation** - Gateway IP + static IP reservations per subnet from a configurable range CIDR

Guest isolation comes from per-range namespaces and dedicated L2 networks rather than VPC-level isolation.

## VM Runtime Lifecycle

Module: `gdc_vmruntime_assets.py`

1. Create `VirtualMachineDisk` from GCS-hosted OS image
2. Wait for disk import to complete
3. Create `VirtualMachine` with disk, network interfaces, and cloud-init/userdata
4. Wait for VM to reach running state
5. Return IP assignments and connection details

Per-profile configuration (vCPU, memory, disk size, image URL) is defined in `GDCVMRuntimeConfig`. SSH keypairs are generated per-range.

## Scenario Pods

Module: `gdc_scenario_pods.py`

Lighter-weight alternative to full VMs. Pods attach to range L2 networks via CNI network attachment annotations. Lower resource overhead, but they are not the parity baseline for features that require full guest semantics.

## VM-Series NGFW on GDC

Module: `gdc_vmseries_ngfw.py`

Provisions Palo Alto Networks VM-Series as KubeVirt VMs with:
- Management + data network interfaces
- Bootstrap disk from GCS bucket
- SSH access via Secret Manager credentials
- Power operations (start/stop)

## Backend Ownership Binding (destroy-after-selector-flip)

`GCP_RANGE_BACKEND` selects which backend a *new* GCP range is admitted on (`gce`
range cells by default, or `gdc` VM Runtime for validation). It is a deploy-wide
selector, not durable ownership. Since #1666 the admitted backend and trusted
instantiation purpose are persisted as a write-once binding on the Engine `Range`
(`range_backend`, `instantiation_purpose`) at provision time, sourced from the
CMS live-fire admission result. Destroy, compensation, retry, and reconciliation
route from that persisted binding (read through the provisioner's request-scoped
database projection), never from a re-read of the selector, so flipping the
deploy selector `gdc -> gce` can no longer route an existing GDC range through the
GCE path and strand its namespaces, VMs, disks, secrets, L2 Networks, and subnet
allocations.

Ranges created before #1666 carry no binding. On destroy the provisioner resolves
their backend only from durable ownership evidence (the `asset_type` discriminant
persisted on each instance's state: `vm_runtime_vm`/`scenario_pod` for GDC,
`gce_vm` for GCE range cells). A range whose evidence is ambiguous or absent fails
closed with a `prerequisite` diagnostic and keeps its cleanup state; back-fill its
binding explicitly, while the historical selector is still known, before retrying:

```bash
python manage.py backfill_range_backend_binding --request-id <uuid> --backend gdc
```

The binding is write-once: the command refuses to overwrite an existing value.

## Configuration

All GDC config is loaded from environment variables and Secret Manager at runtime. Key config structures in `engine/provisioner/config.py`:

| Config | Purpose |
|--------|---------|
| `GDCNetworkAccessConfig` | GDC cluster kubeconfig, VXLAN CIDR, namespace prefix, DNS |
| `GDCVMRuntimeConfig` | Storage class, image URLs and sizing per OS profile |
| `GDCPaloAltoVMSeriesConfig` | VM-Series image, bootstrap bucket, resource sizing |

GDC access credentials are stored in Secret Manager and loaded via `GDC_ACCESS_SECRET_ID`.

## File Locations

```
shifter/engine/provisioner/
├── gdc_range_networks.py      # L2 network provisioning
├── gdc_vmruntime_assets.py    # KubeVirt VM lifecycle
├── gdc_scenario_pods.py       # Pod-based guests
├── gdc_vmseries_ngfw.py       # VM-Series NGFW on GDC
├── config.py                  # Configuration dataclasses
└── templates/                 # Jinja2 templates for K8s manifests
```

## Related Docs

- [GCP Infrastructure](gcp-infrastructure) - GKE cluster and platform services
- [Cloud Adapters](../dev/cloud-adapters) - Protocol-based cloud abstraction
- [Networking](networking) - AWS VPC networking (parallel architecture)
