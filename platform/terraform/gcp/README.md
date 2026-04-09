# GCP Terraform

This tree stages the GCP control-plane path for `gcp-dev`.

Current scope:

- project service enablement
- VPC-native GKE foundation
- dedicated peered range VPC reserved for future Compute Engine range subnets
- Cloud SQL PostgreSQL control-plane database over private IP
- shared Cloud SQL databases for the portal and Guacamole client
- Memorystore Redis for channel-layer and worker coordination
- GKE-oriented runtime contract for ephemeral Jobs
- Artifact Registry repositories for core images
- shared GCS bucket for uploads and agent artifacts
- shared Pub/Sub event topic plus worker subscriptions
- reserved global static IP for the public GKE ingress path
- optional Cloud DNS managed zone and ingress A record for a configured hostname
- Secret Manager runtime bundles, with seeded portal DB/app and Guacamole DB/JSON-auth secrets
- reserved private service networking range
- workload and node service accounts with least-privilege runtime roles
- GCS-backed Terraform state bootstrap in CI

Current non-goals:

- guest VM / NGFW / Compute Engine range infrastructure beyond the shared range-network foundation
- OIDC identity provider provisioning

CI still validates this tree with `terraform init -backend=false` and
`terraform validate` on pull requests. On `gcp-dev` pushes, the workflow
authenticates to GCP, bootstraps a GCS backend bucket named
`${project_id}-terraform-state` if needed, and applies the environment.

The environment outputs now also expose the provider-neutral range-network
contract consumed by the provisioner runtime:

- `range_network_id`
- `range_network_cidr`
- `range_network_region`
- `portal_network_cidrs`
