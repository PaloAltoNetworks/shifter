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
- The GKE control-plane endpoint is private. Bootstrap and CI reach it through
  the IAM-authenticated fleet Connect Gateway; optional authorized networks
  are limited to connected RFC1918 ranges.
- GKE Binary Authorization is enabled (`PROJECT_SINGLETON_POLICY_ENFORCE`) so cluster admission enforces the project's Binary Authorization policy.
- The public application edge is protected with a baseline Cloud Armor policy.
- The GDC workstation and cluster hosts are expected to be private-only and accessed through IAP by bootstrap.
- Platform and range VPCs carry explicit `google_compute_firewall` policy (ADR-008-R4): range ingress is deny-by-default with a single allow rule sourced from `local.portal_network_cidrs` on `var.range_provisioner_ports`; the platform VPC blocks world-open SSH/RDP and allows only Google LB health-check ranges to the GKE nodes. Operator break-glass SSH is gated on `var.operator_admin_cidrs` (empty in dev).
- Cloud SQL deletion protection is on by default (`var.cloud_sql_deletion_protection`, default `true`); the platform control-plane database cannot be destroyed without an explicit, environment-root override.
- Memorystore Redis runs on the STANDARD_HA tier with `auth_enabled = true` and `transit_encryption_mode = "SERVER_AUTHENTICATION"` (ADR-008-R6). The AUTH token lives in a `redis` Secret Manager bundle and is hydrated by the runtime entrypoint just like the DB/app secrets - never in the runtime ConfigMap, generated env, or process argv. Django Channels reads `REDIS_TLS` / `REDIS_PASSWORD` and uses a `rediss://` channels_redis URL host; the helper fails closed if TLS is enabled without a hydrated password.
- GCS buckets stay on Google-managed encryption keys (ADR-008-R5). Customer-managed encryption keys (CMEK) are deferred until an external compliance trigger materializes; see `docs/architecture/gcp-gcs-cmek-preflight.md` for the recorded decision, owner, and review trigger.
- `gdc-bootstrap` now fails before Terraform apply unless your
  deployment-specific override (typically `local.auto.tfvars` for local
  runs, or rendered from GitHub secrets for CI - see
  [`docs/dev/deploy-secrets.md`](../../../docs/dev/deploy-secrets.md))
  provides:
  - `public_hostname`
  - `enable_managed_tls = true`
  - `gke_master_authorized_cidrs = []` for Connect Gateway access, or only
    RFC1918 CIDRs reachable through connected private networks

## Deployment-scoped range-secret project

Every GCP deployment requires a pre-existing Secret Manager project dedicated
to ephemeral range credentials. Set `settings.dynamic_secret_project_id` in the
deployment `shifter.yaml`; `shifter-config render` carries that single value to
Terraform, Terraform publishes it to the runtime as
`GCP_DYNAMIC_SECRET_PROJECT_ID`, and every dynamic writer uses it. The project
must not hold platform bundles, Terraform state, application data, or another
deployment's secrets. The cloud/bootstrap owner creates and retires the project;
application Terraform enables Secret Manager and owns only its workload IAM and
DATA_READ audit configuration.

The deploy identity needs enough authority in that project to enable the Secret
Manager API, define the two Shifter custom roles, maintain project IAM members,
and configure Secret Manager audit logging. Runtime authority is narrower:

- provisioner: unconditioned `secretmanager.secrets.create` on the dedicated
  project parent, because Google authorizes create before the secret exists;
- provisioner: the exact get/update/delete/version/IAM-policy verbs, conditioned
  on the deployment's canonical `shifter-<environment>-dynamic-` prefix and the
  Secret resource type;
- portal: read-only access conditioned on the narrower canonical
  `...-dynamic-participant-` prefix;
- range hosts and VPN gateways: accessor only on their individual secret.

The create-only parent grant can create an arbitrary empty container in this
single-purpose project, but it cannot add/read versions, change IAM, or delete
an out-of-prefix object. It cannot create in the platform project. Monitor
Secret Manager resource/quota usage and have only the bootstrap/operator cleanup
identity remove abandoned out-of-prefix containers; do not grant the runtime
provisioner list or broad cleanup authority.

Creation reconciliation also fails closed when it finds any exact legacy or
canonical read-location container whose first version has not appeared after
the bounded concurrency wait. It does not skip an empty legacy container and
mint a competing canonical guest credential or VPN profile, nor publish a
second value into a container that an in-flight provisioner may own. Retry
first; if the container remains empty, use audit/job evidence to prove no
creator is active, delete that exact container with the bootstrap/operator
cleanup identity, and retry the range operation.

Canonical naming also requires an explicit `ENVIRONMENT` value in the runtime
and rejects values outside the lowercase, single-hyphen deployment grammar.
There is no implicit `dev` namespace: missing or malformed configuration fails
before creating a container.

Operator-created inputs are separate. Declare supported GDC/Vertex references
once in `settings.provisioner_static_secret_refs` as full, versionless
`projects/<project>/secrets/<id>` names. The rendered Terraform map deduplicates
those names for exact per-secret provisioner IAM, and the Terraform output feeds
the same keyed references into runtime env. A missing external secret fails the
apply; there is no project-wide fallback.

### Expand, cut over, drain, contract

1. **Expand:** deploy this code with `dynamic_secret_project_id` explicitly set
   equal to `project_id`. Writers retain legacy names and old ranges are
   unaffected. Populate `provisioner_static_secret_refs` before removing the old
   broad provisioner grant.
2. **Cut over:** pre-create the dedicated project, grant the deploy identity the
   control-plane permissions above, change only `dynamic_secret_project_id`, and
   apply. New secrets use canonical names in the dedicated project. Existing
   legacy references are read first and remain deletable; an unavailable new
   project fails closed and never creates back in the platform project.
3. **Verify:** create and destroy a disposable range, verify participant access,
   and run `scripts/gcp/probe_range_secret_permissions.py` with the real
   provisioner, portal, host/gateway pool, worker, launcher, and node identities.
   The script is plan-only unless
   `--execute` is supplied and cleans its probe secrets with the operator
   identity.
4. **Drain:** destroy or naturally retire every range generation whose persisted
   reference points at the platform project. Vertex key deletion and VPN/guest
   teardown check both exact locations, so revocation remains generation-bound.
   Do not copy payloads or rotate a live range merely to rename its reference.
5. **Contract:** after the legacy inventory is empty, remove the migration-only
   legacy IAM resources and lookup paths in a contract release. Retire the old
   project only after independent inventory and audit-log confirmation; Terraform
   destroy deliberately does not delete either project or live dynamic secrets.

Preview the live probe matrix without cloud mutations, then add `--execute` only
from an operator session that can impersonate the listed service accounts and
create/delete cleanup secrets in the dynamic, platform, and unrelated control
projects:

```bash
python3 scripts/gcp/probe_range_secret_permissions.py \
  --platform-project PLATFORM_PROJECT \
  --dynamic-project RANGE_SECRET_PROJECT \
  --unrelated-project UNRELATED_CONTROL_PROJECT \
  --environment gcp-dev \
  --provisioner-service-account PROVISIONER_GSA \
  --portal-service-account PORTAL_GSA \
  --range-host-service-account ASSIGNED_RANGE_HOST_GSA \
  --peer-range-host-service-account PEER_RANGE_HOST_GSA \
  --gateway-service-account ASSIGNED_GATEWAY_GSA \
  --peer-gateway-service-account PEER_GATEWAY_GSA \
  --workers-service-account WORKERS_GSA \
  --launcher-service-account PROVISIONER_LAUNCHER_GSA \
  --node-service-account GKE_NODE_GSA
```

The probe suppresses provider stderr and payload output. It records a run
correlation ID, principal, permission, resource class, fingerprinted resource,
result, and elapsed propagation time. It proves allowed canonical lifecycle and
participant reads; denied platform-project creation and unrelated-resource
lifecycle; portal read partition and mutation denial; assigned host/gateway
per-secret access with peer-secret negatives; and no dynamic-secret read by
workers, launcher, or the GKE node identity. Its `finally` cleanup uses the
operator identity in both projects, so even an unexpectedly allowed negative
create does not leave a probe container.

### Capacity and cost envelope (checked 2026-09-07)

Recalculate this section against the linked Google sources and the deployment's
actual metrics before cut-over. The checked-in defaults bound both the range-host
and VPN gateway identity pools at 24 concurrent slots. A conservative planning
case of 10 one-version dynamic secrets per active range therefore gives 240
active versions. A full 24-range create wave is approximately 528 Secret Manager
writes (24 × (10 create + 10 add-version + 2 per-secret IAM writes)), leaving
only 72 requests of the current 600-write/minute project quota for retries and
reconcile. Do not overlap that wave with a full drain (another 240 deletes);
pace or batch provisioning when the measured shape exceeds this envelope.

Current Secret Manager limits are 90,000 access, 600 other read, and 600 write
requests per minute per project. A global secret version is additionally soft
limited to 1 access/second and 60 accesses/minute, so a burst against one
participant credential can throttle well before the project quota; the portal's
300-second successful-read cache reduces but does not remove that risk. See
[Secret Manager quotas](https://cloud.google.com/secret-manager/quotas).

At the current US list price, automatic replication counts as one location,
active versions beyond the billing account's first six cost $0.06/version-month,
and accesses beyond the first 10,000 cost $0.03 per 10,000. If those free tiers
are otherwise unused, 240 active versions plus 200,000 monthly accesses is
`(240 - 6) × $0.06 + (200,000 - 10,000) / 10,000 × $0.03 = $14.61/month`.
Management operations are currently free. This excludes audit-log storage and
other GCP services; use the [Secret Manager pricing](https://cloud.google.com/secret-manager/pricing)
page and billing-account currency for rollout approval.

DATA_READ audit logs are disabled by Google by default; this stack enables them.
At current Cloud Logging pricing, the first 50 GiB/project/month of non-network
log storage is free, then ingestion is $0.50/GiB, and retention beyond 30 days
is $0.01/GiB-month. Measure the probe and a representative range-access hour,
project monthly volume from that evidence, and set the sink/retention budget;
do not estimate log size from request count alone. See
[Cloud Logging pricing](https://cloud.google.com/products/observability/pricing)
and [Secret Manager audit logging](https://cloud.google.com/secret-manager/docs/audit-logging).

A service account can have at most 10 keys. Consequently the per-range Vertex
key path cannot support the default 24-slot concurrency unless existing keys
leave enough capacity; the optional shared Vertex-key source avoids per-range
key creation but increases blast radius. Its per-range Secret Manager copy is
still deleted with the range. Multiple keys on one range-Vertex service account
authenticate as the same IAM principal and carry identical permissions:
key-per-range is a revocation handle, not principal isolation (#681). Check the
[service-account key limit](https://cloud.google.com/iam/docs/keys-create-delete)
and current key inventory before rollout.

Secret deletion blocks fresh Secret Manager reads after IAM propagation, but
already delivered guest credentials, cached portal values, downloaded VPN
profiles, minted OAuth tokens, and service-account keys have separate revocation
windows. The rollout owner must record the observed permission-probe propagation
time, allow five minutes for the portal cache, revoke the guest/gateway material,
and verify the Vertex key deletion independently. The extra project also consumes
the organization's project quota and requires billing/API/audit-policy authority;
verify those deployment-specific limits rather than assuming project creation is
available.

See also Google's
[IAM resource attributes](https://cloud.google.com/iam/docs/conditions-attribute-reference)
and [Data Access audit configuration](https://cloud.google.com/logging/docs/audit/configure-data-access).

## Email delivery (optional)

GCP has no native Amazon SES equivalent, so a GCP deployment sends transactional
mail (sign-up verification, password reset, invitations) through an operator-chosen
SaaS - SendGrid or Mailgun - using `django-anymail`. Email is optional: with
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
   only - it is never exposed in `ps` output or shell history. Alternatively,
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
- `gke_master_authorized_cidrs = []`; operator and CI access use Connect Gateway

Operational note:

- `create_dns_managed_zone = false` is intentional. DNS is assumed to be managed outside this Terraform tree for now. `shifter.example.com` must resolve to the reserved ingress IP before the Google-managed certificate will become active.
