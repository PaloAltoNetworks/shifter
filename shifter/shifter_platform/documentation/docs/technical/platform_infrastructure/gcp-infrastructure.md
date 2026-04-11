# GCP Infrastructure

GKE-based deployment of the Shifter platform on Google Cloud.

## Directory Structure

```
platform/
├── terraform/gcp/
│   ├── modules/platform-core/    # All GCP infrastructure
│   └── environments/gcp-dev/     # Environment config
├── charts/shifter/               # Helm chart for the control plane
└── k8s/gcp/                      # Base manifests and generated deployment assets
```

Terraform provisions GCP resources. The Shifter control plane is packaged as a Helm chart, and bootstrap renders generated values from Terraform outputs plus Secret Manager payloads before installing the chart.

## Terraform Module: platform-core

Single module provisions the entire GCP control plane.

| Resource | Service | Purpose |
|----------|---------|---------|
| **VPC Networks** (×2) | VPC | `platform` (GKE, shared services) and `range` (guest isolation) |
| **GKE Cluster** | GKE | Private nodes, VPC-native, Workload Identity enabled, public control-plane endpoint restricted by authorized CIDRs |
| **Node Pools** (×3) | GKE | `web` (portal, Guacamole), `workers` (domain workers), `provisioner` (range provisioning jobs) |
| **Cloud SQL** | Cloud SQL | PostgreSQL. Hosts platform DB and Guacamole DB. Private IP only. |
| **Memorystore** | Memorystore | Redis. Channel layer and worker coordination. |
| **Pub/Sub** | Pub/Sub | Event topic with per-domain subscriptions (cms, engine, mc, experiments). |
| **Artifact Registry** | Artifact Registry | Container repositories (portal, guacd, guacamole-client, pulumi-provisioner). |
| **Secret Manager** | Secret Manager | Runtime secret bundles (app, db, guacamole-db, oidc, guacamole-json-auth). |
| **Cloud DNS** | Cloud DNS | Optional. Public hostname with Google-managed TLS certificate. |
| **Cloud Armor** | Cloud Armor | Baseline WAF policy attached to the public portal and Guacamole GKE backends. |
| **GCS Buckets** | Cloud Storage | Assets/artifacts and Terraform state. |
| **Service Accounts** | IAM | Separate accounts for GKE nodes and workloads (portal, workers, provisioner). Workload Identity binds K8s SAs to GCP SAs. |

## GKE Cluster

Private nodes with no public node IPs. Cloud NAT provides outbound connectivity.

- **Release channel**: REGULAR (automatic patching)
- **Workload Identity**: Enabled. Pod service accounts map to GCP service accounts.
- **Networking**: VPC-native with secondary IP ranges for pods and services
- **Logging/Monitoring**: System components and workload logging enabled
- **Control-plane access**: public endpoint retained for bootstrap compatibility, restricted by authorized CIDRs

### Node Pools

| Pool | Role | Notes |
|------|------|-------|
| `web` | Portal and Guacamole | Handles user-facing traffic |
| `workers` | CMS, Engine, MC background workers | Queue consumers |
| `provisioner` | Range provisioning jobs | Runs K8s Jobs for range lifecycle |

Machine types and node counts are configurable per environment.

## Kubernetes Workloads

Managed via Helm with base chart defaults, environment values, and bootstrap-generated runtime values.

### Chart Resources (`platform/charts/shifter/templates/`)

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
| `portal-backendconfig.yaml` | Portal health check + Cloud Armor attachment |
| `guacamole-backendconfig.yaml` | Guacamole Cloud Armor attachment |
| `ingress.yaml` | Public ingress, managed certificate, HTTPS redirect |

### Values files

- `platform/charts/shifter/values.yaml` - chart defaults
- `platform/charts/shifter/values-gcp-dev.yaml` - `gcp-dev` overrides
- `platform/charts/shifter/values-gcp-prod.yaml` - `gcp-prod` overrides
- bootstrap-generated values - live Terraform outputs, runtime env, image roots, secret payloads, and edge policy names

## Networking

Dual-network design, same pattern as AWS (see [Networking](networking)).

| Network | Purpose |
|---------|---------|
| `platform` | GKE cluster, Cloud SQL (Private Services Access), Memorystore |
| `range` | Guest subnets for range instances. Cloud Router + NAT for egress. |

Networks are peered bidirectionally for platform-to-range connectivity.

GDC deployments use custom L2 networks (VXLAN-based) for per-range guest isolation instead of VPC subnets.

## Deployment Path

The authoritative GCP bring-up path on this branch is the bootstrap entrypoint:

```bash
./scripts/bootstrap/deploy.py gdc-bootstrap --project-id prod-rwctxzl6shxk --cluster-id cluster1
```

That flow:

1. reconciles the GDC substrate
2. applies GCP Terraform
3. builds and pushes control-plane images
4. renders secure runtime env values from Terraform outputs and Secret Manager
5. renders generated Helm values
6. installs or upgrades the Shifter chart
7. waits for rollout and managed-certificate convergence

GitHub Actions validation for `gcp-dev` still exists, but the staged workflow is not the authoritative deployment contract until it is reconciled with the Helm/bootstrap path.

## Current `gcp-dev` concrete values

- Project: `prod-rwctxzl6shxk`
- Hostname: `shifter.keplerops.com`
- Managed TLS: enabled
- Current authorized admin CIDR: `173.181.31.170/32` from the WSL bootstrap host as of 2026-04-11

If the operator egress IP changes, `gke_master_authorized_cidrs` must be updated before the next bootstrap.

## Related Docs

- [Cloud Adapters](../dev/cloud-adapters) - Protocol-based cloud abstraction
- [Networking](networking) - VPC/network architecture (AWS section)
- [Secrets](../dev/secrets) - Secret management across clouds
- [CI/CD](../dev/ci-cd) - Full CI/CD documentation including GCP workflows
- [Terraform](../dev/terraform) - Terraform conventions and GCP module patterns
