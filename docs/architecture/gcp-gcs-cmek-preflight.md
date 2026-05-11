# GCP GCS CMEK Preflight

Issue: GitHub #962, "[MEDIUM] No CMEK encryption on GCS buckets".

This note records the architecture boundary for either remediating GCS bucket
encryption with customer-managed keys or accepting Google-managed encryption as
an explicit design decision. It is not an implementation plan.

## Decision Boundary

The issue covers two buckets with different owners and lifecycles:

- the platform assets bucket, owned by
  `platform/terraform/gcp/modules/platform-core/main.tf`
- the Terraform state bucket, created before Terraform init by the GCP deploy
  workflow and by the bootstrap/recovery harness

If the compliance posture requires CMEK, both bucket roles need an explicit
Cloud KMS key contract. Do not create only a Terraform-managed KMS key inside
`platform-core` and then try to use it for Terraform state; the state bucket
exists before that Terraform state can be initialized. The state-bucket key
must be available at bootstrap time, either through a deterministic
bootstrap-managed KMS key or through an externally supplied key name.

If the product decision is to accept Google-managed encryption instead, record
that as a dated architecture/security decision with an owner and review point.
Do not leave the red-team finding closed only by issue discussion.

## Canonical Incumbents

- `platform/terraform/gcp/modules/platform-core/main.tf`: owns the assets
  bucket, audit-log bucket, service enablement, common labels, workload IAM,
  Secret Manager runtime bundles, and GCP service accounts.
- `platform/terraform/gcp/modules/platform-core/variables.tf`: canonical
  module input validation layer for GCP platform security settings.
- `platform/terraform/gcp/environments/gcp-dev/main.tf` and `variables.tf`:
  environment-owned seam for passing security configuration into
  `platform-core`.
- `.github/workflows/_gcp-dev.yml`: normal deploy path that creates/updates
  the GCS Terraform state bucket before `terraform init`.
- `scripts/bootstrap/deploy.py`: operator bootstrap/recovery path that creates
  the same Terraform state bucket name via
  `GDCBootstrapConfig.terraform_state_bucket_name`.
- `platform/terraform/gcp/README.md` and
  `shifter/shifter_platform/documentation/docs/technical/platform_infrastructure/gcp-infrastructure.md`:
  operator-facing GCP infrastructure contract.
- `.tflint.hcl`, `.github/workflows/_quality.yml`, and
  `scripts/adr_guard/adr_guard.py`: repo-wide architecture and stack-native
  validation entrypoints.

## Cross-Cutting Layers

Security layers the design must satisfy:

- Terraform resource policy: the assets bucket encryption setting belongs on
  `google_storage_bucket.assets` at the existing `platform-core` boundary.
  Avoid a second GCS module or application-side upload flag for bucket default
  encryption.
- Bootstrap state policy: the Terraform state bucket is not owned by
  `platform-core`. If CMEK is required, `_gcp-dev.yml` and
  `scripts/bootstrap/deploy.py` must converge on the same state-bucket KMS key
  naming or input contract before `terraform init`.
- Cloud KMS service enablement: `cloudkms.googleapis.com` must be enabled
  before creating or using a key. If Terraform owns KMS for the assets bucket,
  add it to the existing `local.required_services`; if bootstrap owns the state
  key, enable it in the bootstrap/workflow layer too.
- KMS location shape: a Cloud Storage bucket's default KMS key must be in a
  location compatible with the bucket location. The current GCP bucket location
  is `var.region`, so the key contract must be region-aware and must not hard
  code a global or unrelated location.
- KMS IAM: the Cloud Storage project service agent for the project must be
  granted KMS encrypter/decrypter access on any key used as a bucket default.
  The deploy/bootstrap identity also needs the minimum permissions required to
  create or reference the key and set bucket default encryption.
- Terraform input shape: use narrow key-name inputs where a key is supplied
  from outside the owning layer. A boolean such as `enable_cmek` is not enough
  because it hides key ownership, location, rotation, and IAM policy.
- Workflow validation: keep using Terraform fmt/init/validate, tflint, and
  actionlint. If shell workflow logic grows to parse more than simple scalar
  values, move that logic into a small tested script rather than adding another
  fragile `awk` parser for HCL.
- Secret handling: KMS key resource names are configuration, not secrets. Do
  not store them in Secret Manager, Kubernetes Secrets, GitHub secrets, or
  runtime secret bundles unless a future provider requires a genuinely secret
  credential.
- Runtime env-binding: GCS CMEK is an infrastructure encryption policy. It
  must not change `scripts/gcp/render_runtime_env.py`, Helm values, Django
  settings, storage adapter protocols, upload DTOs, or provisioner runtime env.
- Auth surface: do not expand Workload Identity, portal object-storage roles,
  Identity Platform, or application auth to compensate for KMS permissions.
  KMS use belongs to bucket service agents and deploy/bootstrap identities.
- OS/process exposure: key names and bucket names may appear in Terraform and
  gcloud argv. Tokens, service-account JSON, access tokens, and secret payloads
  must stay in the existing GCP auth path and must not be echoed or composed
  into shell strings.
- Error envelopes: failed CMEK setup should fail through Terraform validation,
  provider errors, actionlint/tflint, or bootstrap `error(...)` exits. Do not
  add application exception types or user-facing error envelopes for bucket
  encryption posture.
- Observability: rely on Terraform plans, bucket metadata, Cloud KMS audit
  logs, and GCS access logs. Do not add application logging that claims to
  audit encryption state.

## Extensibility Seam

The seam is a bucket-role-specific KMS key contract:

- assets bucket: a module/environment input such as
  `assets_bucket_kms_key_name`, defaulting to null only if Google-managed
  encryption remains an accepted posture
- Terraform state bucket: a bootstrap/workflow input or deterministic
  bootstrap-managed key name available before Terraform init

Keep the seam bucket-role-specific. The next reasonable variation is separate
keys or rotation/IAM policy per bucket role; that should not require editing
application code or replacing the GCP platform module.

## Gotchas

- Terraform state is the bootstrap cycle. A KMS key created by the same
  Terraform state cannot protect that state bucket before init.
- The assets bucket currently logs to the audit-log bucket. If CMEK policy is
  added to one storage bucket, decide explicitly whether the audit-log bucket
  is in scope too; do not silently create mixed encryption posture unless that
  is the accepted design.
- GCS bucket CMEK is not object signing, signed URL auth, lifecycle policy,
  public-access prevention, retention, versioning, or audit logging. Keep
  those controls separate.
- Key destruction or disabling can make state and assets unavailable. Treat
  KMS lifecycle operations as break-glass actions with recovery guidance, not
  routine cleanup.
- A single generic "platform encryption key" can become a leaky abstraction
  across state, assets, logs, Secret Manager, Cloud SQL, Artifact Registry,
  and future range artifacts. Scope keys by resource role unless an explicit
  security decision says otherwise.
- The GCP storage adapters in portal and provisioner should continue to call
  normal GCS APIs. Supplying per-object KMS keys from runtime code would
  duplicate the bucket default policy and widen the runtime auth surface.

## Non-Goals

- Do not redesign object-storage adapters, upload sessions, signed URL flows,
  DTOs, repositories, service classes, or application exception hierarchies.
- Do not migrate Terraform state, rename buckets, split the platform-core
  module, or introduce a second deployment workflow as part of this issue.
- Do not change Cloud SQL, Secret Manager payload schemas, Identity Platform,
  GKE control-plane access, Cloud Armor, Workload Identity bindings, or
  Kubernetes manifests unless the CMEK implementation directly requires it.
- Do not use committed plaintext credentials or service-account keys to make
  KMS setup convenient.
- Do not close the finding by adding comments only in Terraform; either wire a
  concrete CMEK contract or record the accepted Google-managed encryption
  decision in architecture/security documentation.

## Validation

Run the repo-required checks for touched surfaces:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
cd platform/terraform && tflint --recursive --config ../../.tflint.hcl
cd platform/terraform/gcp/environments/gcp-dev && terraform init -backend=false && terraform validate
```

If the implementation changes `.github/workflows/_gcp-dev.yml`, also run
`actionlint`. If it changes `scripts/bootstrap/deploy.py`, run the bootstrap
test subset covering GCP control-plane/bootstrap behavior.

## Outcome — accepted Google-managed encryption (2026-05-11)

Landed alongside #959, #960, and #963. The architectural decision recorded
in ADR-008-R5 (`docs/adr/index.yaml`) is the implementation record:

- **Decision**: GCP GCS bucket encryption stays on Google-managed keys for
  the current scope.
- **Rationale**: no compliance driver currently justifies the operational
  cost of bucket-role-specific KMS keys, KMS service-agent IAM, and a
  state-bucket bootstrap KMS contract. The state bucket boots before
  Terraform owns any KMS resource, so adding CMEK would require a
  separate bootstrap-layer key contract.
- **Scope**: covers the platform assets bucket
  (`google_storage_bucket.assets`), the audit-logs bucket
  (`google_storage_bucket.audit_logs`), and the Terraform state bucket
  bootstrapped by `.github/workflows/_gcp-dev.yml` /
  `scripts/bootstrap/deploy.py`.
- **Owner**: platform infra.
- **Review trigger**: an external compliance requirement (FedRAMP / SOC 2
  Type II contract, GovCloud-style customer asks, or an explicit security
  review).
- **Non-decision**: this is not a deferral; the workflow's no-defer rule
  applies. If the trigger fires later, the work is a new issue against
  the bucket-role-specific KMS contract described in this preflight, not
  a follow-up on #962.

No code change shipped in the security-hardening PR for #962; the ADR
rule and this outcome section are the durable record.
