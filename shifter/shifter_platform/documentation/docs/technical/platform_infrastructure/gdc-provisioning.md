# GDC Range Provisioning

Range guest provisioning on Google Distributed Cloud (GDC). GDC uses KubeVirt for VM workloads and Kubernetes-native networking for guest isolation.

On AWS, ranges are EC2 instances in isolated VPC subnets. On GDC, ranges are either KubeVirt VMs or lightweight pods on a GDC cluster, connected via custom L2 networks.

## Asset Types

The provisioner supports three GDC asset types, selected per-scenario:

| Type | Module | What It Creates | Use Case |
|------|--------|----------------|----------|
| **VM Runtime** | `gdc_vmruntime_assets.py` | `VirtualMachine` + `VirtualMachineDisk` CRDs | Full OS guests (Kali, Ubuntu, Windows, Domain Controller) |
| **Scenario Pods** | `gdc_scenario_pods.py` | Kubernetes Pods with network attachments | Lightweight container-based guests (lower overhead) |
| **VM-Series NGFW** | `gdc_vmseries_ngfw.py` | VM-Series firewall VMs on GDC VM Runtime | Palo Alto Networks NGFW integration |

Mixed ranges can combine VMs and pods on the same L2 network.

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

Lighter-weight alternative to full VMs. Pods attach to range L2 networks via CNI network attachment annotations. Supports Kali and Ubuntu container images. Lower resource overhead but no Windows or bare-metal OS support.

## VM-Series NGFW on GDC

Module: `gdc_vmseries_ngfw.py`

Provisions Palo Alto Networks VM-Series as KubeVirt VMs with:
- Management + data network interfaces
- Bootstrap disk from GCS bucket
- SSH access via Secret Manager credentials
- Power operations (start/stop)

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
