# GCP Terraform

This tree provisions the GCP control plane for Shifter.

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
- Cloud Armor security policy for the public ingress backends
- optional Cloud DNS managed zone and ingress A record for a configured hostname
- Secret Manager runtime bundles, with seeded portal DB/app and Guacamole DB/JSON-auth secrets
- Identity Platform corporate auth with FirebaseUI/browser-side Google auth flows, allowlisted self-signup, required email verification, required TOTP MFA before app-session creation, and bootstrap-owned first-operator seeding
- reserved private service networking range
- workload and node service accounts with least-privilege runtime roles
- GCS-backed Terraform state bootstrap in CI

Security posture:

- GKE nodes are private-only.
- The GKE control-plane endpoint remains public for now because bootstrap still runs `get-credentials` and Helm from the operator machine, but access is restricted with `master_authorized_networks_config`.
- GKE Binary Authorization is enabled (`PROJECT_SINGLETON_POLICY_ENFORCE`) so cluster admission enforces the project's Binary Authorization policy.
- The public application edge is protected with a baseline Cloud Armor policy.
- The GDC workstation and cluster hosts are expected to be private-only and accessed through IAP by bootstrap.
- Platform and range VPCs carry explicit `google_compute_firewall` policy (ADR-008-R4): range ingress is deny-by-default with a single allow rule sourced from `local.portal_network_cidrs` on `var.range_provisioner_ports`; the platform VPC blocks world-open SSH/RDP and allows only Google LB health-check ranges to the GKE nodes. Operator break-glass SSH is gated on `var.operator_admin_cidrs` (empty in dev).
- Cloud SQL deletion protection is on by default (`var.cloud_sql_deletion_protection`, default `true`); the platform control-plane database cannot be destroyed without an explicit, environment-root override.
- Memorystore Redis runs on the STANDARD_HA tier with `auth_enabled = true` and `transit_encryption_mode = "SERVER_AUTHENTICATION"` (ADR-008-R6). The AUTH token lives in a `redis` Secret Manager bundle and is hydrated by the runtime entrypoint just like the DB/app secrets — never in the runtime ConfigMap, generated env, or process argv. Django Channels reads `REDIS_TLS` / `REDIS_PASSWORD` and uses a `rediss://` channels_redis URL host; the helper fails closed if TLS is enabled without a hydrated password.
- GCS buckets stay on Google-managed encryption keys (ADR-008-R5). Customer-managed encryption keys (CMEK) are deferred until an external compliance trigger materializes; see `docs/architecture/gcp-gcs-cmek-preflight.md` for the recorded decision, owner, and review trigger.
- `gdc-bootstrap` now fails before Terraform apply unless your
  deployment-specific override (typically `local.auto.tfvars` for local
  runs, or rendered from GitHub secrets for CI — see
  [`docs/dev/deploy-secrets.md`](../../../docs/dev/deploy-secrets.md))
  provides:
  - `public_hostname`
  - `enable_managed_tls = true`
  - at least one `gke_master_authorized_cidrs` entry

## Email delivery (optional)

GCP has no native Amazon SES equivalent, so a GCP deployment sends transactional
mail (sign-up verification, password reset, invitations) through an operator-chosen
SaaS — SendGrid or Mailgun — using `django-anymail`. Email is optional: with
`email_backend` unset (the default) the portal uses Django's console backend and
no email secret is created.

To enable email:

1. Set the email variables in your environment override (for example
   `local.auto.tfvars`, or rendered from CI secrets):

   ```hcl
   # SendGrid
   email_backend      = "anymail.backends.sendgrid.EmailBackend"
   email_from_address = "noreply@your-domain.example"

   # or Mailgun
   email_backend       = "anymail.backends.mailgun.EmailBackend"
   email_from_address  = "noreply@your-domain.example"
   email_sender_domain = "mg.your-domain.example"
   ```

2. `terraform apply`. Terraform creates an **unseeded** Secret Manager secret
   `${project_id-prefix}-email` for the ESP API key. The key is never stored in
   Terraform state, tfvars, Helm values, or this repo.

3. Populate the secret with your ESP API key as a JSON bundle (the runtime
   entrypoint reads the `api_key` field). Read the key from a silent prompt so
   it never lands in shell history, command lines, or process arguments:

   ```bash
   read -rs -p "ESP API key: " ESP_API_KEY && echo
   printf '{"api_key":"%s"}' "$ESP_API_KEY" \
     | gcloud secrets versions add "${PROJECT_PREFIX}-email" --data-file=- --project "$PROJECT_ID"
   unset ESP_API_KEY
   ```

   `printf` is a shell builtin, so the key passes through the variable and stdin
   only — it is never exposed in `ps` output or shell history. Alternatively,
   write the JSON to a `chmod 600` file and pass it with `--data-file=<path>`.

The deploy renderer (`scripts/gcp/render_runtime_env.py`) emits `EMAIL_BACKEND`,
`DEFAULT_FROM_EMAIL`, the secret **reference** `EMAIL_API_KEY_SECRET_ID`, and (for
Mailgun) `MAILGUN_SENDER_DOMAIN`; the entrypoint hydrates the key into
`EMAIL_API_KEY` at startup. See `shifter/shifter_platform/config/_email.py` for
the backend selection.

Current non-goals:

- guest VM / NGFW / Compute Engine range infrastructure beyond the shared range-network foundation

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

`gcp-dev` concrete values:

- `project_id = "prod-rwctxzl6shxk"`
- `public_hostname = "shifter.example.com"`
- `enable_managed_tls = true`
- `gke_master_authorized_cidrs = ["173.181.31.170/32"]` as of 2026-04-11 from the current WSL operator egress

Operational note:

- `create_dns_managed_zone = false` is intentional. DNS is assumed to be managed outside this Terraform tree for now. `shifter.example.com` must resolve to the reserved ingress IP before the Google-managed certificate will become active.
