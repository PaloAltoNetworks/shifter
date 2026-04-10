# GCP Infrastructure

GKE-based deployment of the Shifter platform on Google Cloud.

## Directory Structure

```
platform/
├── terraform/gcp/
│   ├── modules/platform-core/    # All GCP infrastructure
│   └── environments/gcp-dev/     # Environment config
└── k8s/gcp/
    ├── base/                     # Kubernetes manifests
    └── overlays/gcp-dev/         # Environment-specific patches
```

Terraform provisions GCP resources. Kustomize manages Kubernetes workloads. CI/CD bridges them: Terraform outputs feed Kustomize ConfigMaps via render scripts.

## Terraform Module: platform-core

Single module provisions the entire GCP control plane.

| Resource | Service | Purpose |
|----------|---------|---------|
| **VPC Networks** (×2) | VPC | `platform` (GKE, shared services) and `range` (guest isolation) |
| **GKE Cluster** | GKE | Private cluster, VPC-native, Workload Identity enabled |
| **Node Pools** (×3) | GKE | `web` (portal, Guacamole), `workers` (domain workers), `provisioner` (range provisioning jobs) |
| **Cloud SQL** | Cloud SQL | PostgreSQL. Hosts platform DB and Guacamole DB. Private IP only. |
| **Memorystore** | Memorystore | Redis. Channel layer and worker coordination. |
| **Pub/Sub** | Pub/Sub | Event topic with per-domain subscriptions (cms, engine, mc, experiments). |
| **Artifact Registry** | Artifact Registry | Container repositories (portal, guacd, guacamole-client, pulumi-provisioner). |
| **Secret Manager** | Secret Manager | Runtime secret bundles (app, db, guacamole-db, oidc, guacamole-json-auth). |
| **Cloud DNS** | Cloud DNS | Optional. Public hostname with Google-managed TLS certificate. |
| **GCS Buckets** | Cloud Storage | Assets/artifacts and Terraform state. |
| **Service Accounts** | IAM | Separate accounts for GKE nodes and workloads (portal, workers, provisioner). Workload Identity binds K8s SAs to GCP SAs. |

## GKE Cluster

Private cluster with no public node IPs. Cloud NAT provides outbound connectivity.

- **Release channel**: REGULAR (automatic patching)
- **Workload Identity**: Enabled. Pod service accounts map to GCP service accounts.
- **Networking**: VPC-native with secondary IP ranges for pods and services
- **Logging/Monitoring**: System components and workload logging enabled

### Node Pools

| Pool | Role | Notes |
|------|------|-------|
| `web` | Portal and Guacamole | Handles user-facing traffic |
| `workers` | CMS, Engine, MC background workers | Queue consumers |
| `provisioner` | Range provisioning jobs | Runs K8s Jobs for range lifecycle |

Machine types and node counts are configurable per environment.

## Kubernetes Workloads

Managed via Kustomize with base manifests and per-environment overlays.

### Base Resources (`platform/k8s/gcp/base/`)

| Manifest | Workload |
|----------|----------|
| `web-deployment.yaml` | Portal Django app |
| `guacd-deployment.yaml` | Guacamole protocol daemon |
| `guacamole-client-deployment.yaml` | Guacamole web client |
| `worker-cms-deployment.yaml` | CMS queue consumer |
| `worker-engine-deployment.yaml` | Engine queue consumer |
| `worker-mc-deployment.yaml` | Mission Control queue consumer |
| `ctf-scheduler-deployment.yaml` | CTF batch scheduler |
| `rbac-job-launcher.yaml` | RBAC for provisioner K8s Jobs |
| `serviceaccounts.yaml` | K8s service accounts (portal, workers, provisioner) |

### Overlays (`platform/k8s/gcp/overlays/{env}/`)

- Image retagging to Artifact Registry paths
- ConfigMap generation from static + Terraform-generated env files
- Workload Identity annotations on service accounts
- Ingress and FrontendConfig (generated at deploy time)

## Networking

Dual-network design, same pattern as AWS (see [Networking](networking)).

| Network | Purpose |
|---------|---------|
| `platform` | GKE cluster, Cloud SQL (Private Services Access), Memorystore |
| `range` | Guest subnets for range instances. Cloud Router + NAT for egress. |

Networks are peered bidirectionally for platform-to-range connectivity.

GDC deployments use custom L2 networks (VXLAN-based) for per-range guest isolation instead of VPC subnets.

## CI/CD

GitHub Actions workflow per environment (e.g., `_gcp-dev.yml`).

**Validate** (on PR): Terraform fmt/validate, Kustomize render + kubeconform schema check.

**Deploy** (on push to target branch):
1. Authenticate via Workload Identity Federation (OIDC)
2. `terraform apply`
3. Generate runtime ConfigMap from Terraform outputs (`scripts/gcp/render_runtime_env.py`)
4. Generate Ingress manifest (`scripts/gcp/render_edge_manifest.py`)
5. Apply Kubernetes manifests
6. Sync secrets into K8s Secrets
7. Roll deployments
8. Apply edge resources (Ingress, managed certificate, FrontendConfig)

## Related Docs

- [Cloud Adapters](../dev/cloud-adapters) - Protocol-based cloud abstraction
- [Networking](networking) - VPC/network architecture (AWS section)
- [Secrets](../dev/secrets) - Secret management across clouds
- [CI/CD](../dev/ci-cd) - Full CI/CD documentation including GCP workflows
- [Terraform](../dev/terraform) - Terraform conventions and GCP module patterns
