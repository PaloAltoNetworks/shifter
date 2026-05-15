# GKE Deployment Assets

This tree contains the GCP/GKE deployment assets that support the Helm-based Shifter control-plane rollout.

Current scope:

- Helm chart packaging for the Shifter control plane (`platform/charts/shifter`)
- chart-owned portal, worker, scheduler, `guacd`, and `guacamole-client` workloads
- chart-owned Services, service accounts, RBAC, runtime ConfigMap, and Guacamole Secret
- GKE Ingress resources with Google-managed certificate and HTTPS redirect support
- chart-owned `BackendConfig` resources for:
  - portal health checks
  - Cloud Armor attachment on the public portal backend
  - Cloud Armor attachment on the public Guacamole backend
- generated runtime values derived from Terraform outputs and bootstrap-owned secret fetches
- secure portal runtime contract for the GCP Identity Platform + FirebaseUI auth path
- generated range-network env contract for provisioner jobs
- bootstrap-driven rollout via `helm upgrade --install`

Current non-goals:

- VM / NGFW runtime integration

Deployment model:

- Base chart defaults live in `platform/charts/shifter/values.yaml`.
- Environment overrides live in `platform/charts/shifter/values-gcp-dev.yaml` and `platform/charts/shifter/values-gcp-prod.yaml`.
- Bootstrap renders a final generated values file from live Terraform outputs and Secret Manager payloads, then applies the chart.
- GCP bootstrap now always renders the secure runtime path. It no longer silently falls back to the public IP/debug/dev-login path.
- Runtime config can elevate the bootstrap operator through `PLATFORM_BOOTSTRAP_STAFF_EMAILS` and `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS` without committing identities to the chart.
- GCP `/login/` is a thin browser shell that hosts Identity Platform's FirebaseUI widget. Django only exchanges a verified Google identity token for an app session; it does not process portal credentials server-side.
- Public `/oidc/authenticate/` requests on GCP are redirected to `/login/` so the AWS OIDC entrypoint remains stable without exposing a dead GCP URL.

Security posture:

- Portal and Guacamole are the only intended public backends.
- Both public backends attach to a Cloud Armor policy through `BackendConfig`.
- The public hostname for `gcp-dev` is `shifter.example.com`.
- Managed TLS is required for bootstrap.
- DNS is currently expected to be managed outside this tree, so the hostname must be pointed at the ingress IP for certificate activation.

The generated runtime env now carries the provider-neutral range-network
contract and the GDC access settings used by the provisioner for the active
GDC range plane:

- `RANGE_NETWORK_ID`
- `RANGE_NETWORK_CIDR`
- `RANGE_NETWORK_REGION`
- `PORTAL_NETWORK_CIDRS`
- `GDC_ACCESS_SECRET_ID`
- `GDC_RANGE_NAMESPACE_PREFIX`
- `GDC_NETWORK_INTERFACE`
- `GDC_NETWORK_DNS_NAMESERVERS`
- `GDC_STATIC_IP_RESERVATION_COUNT`
