# GKE Manifests

This tree stages the GKE-native control-plane deployment path for `gcp-dev`.

Current scope:

- Django web deployment
- GKE-native `guacd` and `guacamole-client` deployments
- CMS, Engine, and Mission Control worker deployments
- CTF scheduler deployment
- Kubernetes namespaces, service accounts, and RBAC for the Job-launching path
- `kustomize` overlay for `gcp-dev`
- generated runtime ConfigMap values derived from Terraform outputs
- generated range-network env contract for ephemeral provisioner Jobs
- generated edge manifest for `/` and `/guacamole`
- optional hostname-aware ingress rules with Google-managed certificate annotations and HTTPS redirect FrontendConfig
- rollout automation on `gcp-dev` pushes after images are pushed to Artifact Registry
- namespace Secret sync for Guacamole runtime credentials sourced from Secret Manager
- conditional enablement of the non-debug OIDC portal path when hostname, TLS, OIDC secret readiness, and managed-certificate readiness all line up

Current non-goals:

- VM / NGFW runtime integration

CI renders the `gcp-dev` overlay with `kubectl kustomize` and validates the
rendered output together with the committed generated edge manifest using
`kubeconform` on every PR. Pushes to `gcp-dev` also render the runtime env file
and edge manifest from Terraform outputs, apply the workloads to GKE, sync the
Guacamole namespace Secret, roll the deployments, apply the edge resources, and
promote the runtime from the IP/debug path to the hostname/TLS path once the
managed certificate becomes active.

The generated runtime env now carries the provider-neutral range-network
contract for future Compute Engine slices:

- `RANGE_NETWORK_ID`
- `RANGE_NETWORK_CIDR`
- `RANGE_NETWORK_REGION`
- `PORTAL_NETWORK_CIDRS`
