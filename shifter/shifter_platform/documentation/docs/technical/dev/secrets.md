# Secrets Management

Where secrets live and how to manage them.

## Principles

1. **Never in code** - No secrets in source files or environment configs
2. **GitHub Secrets for CI/CD** - OIDC role ARNs only
3. **Cloud secret manager for runtime** - AWS Secrets Manager today, GCP Secret Manager for `gcp-dev`
4. **Explicit, not default** - No silent fallbacks; fail if secret missing
5. **tfvars are config, not secrets** - Committed to repo, no sensitive values

## GitHub Secrets

These must be configured in repository Settings > Secrets and variables > Actions.

| Secret | Purpose |
|--------|---------|
| `AWS_ROLE_ARN` | GitHub Actions IAM role for **prod** (OIDC) |
| `AWS_ROLE_ARN_DEV` | GitHub Actions IAM role for **dev** (OIDC) |
| `GCP_SERVICE_ACCOUNT` | GitHub Actions service account email for `gcp-dev` deploys |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | GitHub Actions workload identity provider resource for `gcp-dev` deploys |
| `GCP_BOOTSTRAP_ADMIN_EMAIL` | Optional first GCP operator email for Identity Platform bootstrap |
| `GCP_BOOTSTRAP_ADMIN_PASSWORD` | Optional first GCP operator password for Identity Platform bootstrap |
| `PLATFORM_BOOTSTRAP_STAFF_EMAILS` | Optional comma-separated runtime staff bootstrap emails for production auth providers |
| `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS` | Optional comma-separated runtime superuser bootstrap emails for production auth providers |

AWS uses IAM role ARNs for OIDC federation. `gcp-dev` uses Google workload
identity federation. No static access keys are required.

**Note**: Terraform variables (tfvars) are committed to the repository. CI/CD reads them directly from the checked-out code. No `TF_VARS_*` secrets needed.

## AWS Secrets Manager

Runtime secrets accessed by the portal at startup.

### Portal Secrets

| Secret Name | Contains |
|-------------|----------|
| `shifter-{env}-portal-db-credentials` | RDS connection (host, port, user, password, dbname) |
| `shifter-{env}-portal-app` | Django SECRET_KEY, other app secrets |
| `shifter-{env}-portal-cognito` | OIDC client ID, client secret, domain |
| `shifter-{env}-portal-dc-domain` | Domain-controller domain Administrator password (`DC_DOMAIN_PASSWORD`) — used by the engine provisioner to promote prebaked DC AMIs and to domain-join victims |

The domain-controller password is a live credential. It must not appear in
committed tfvars, workflow YAML, Terraform plan comments, or command logs —
only in Secrets Manager and (like every other portal secret) in restricted
Terraform state.

#### Provisioning (Terraform-managed)

The DC domain password secret is created and seeded by the engine-provisioner
module (`platform/terraform/modules/engine-provisioner/secrets.tf`), exactly
like the portal RDS credentials and the Django-app secret: a `random_password`
generated at apply time and stored in `aws_secretsmanager_secret.dc_domain_password`
via an `aws_secretsmanager_secret_version`. `terraform apply` for the portal
stack creates the secret with a live `AWSCURRENT` value and wires its ARN into
the engine ECS task definition (`secrets = [...]`) and the portal SSM parameter
(`${ps_prefix}/dc-domain-password-secret-arn`). The engine provisioner uses
that value to promote each prebaked DC AMI (the AMI ships AD DS binaries; the
domain — and its Administrator password — is created per range at provision
time) and to domain-join victims; the portal Django container reads it at
runtime via `entrypoint.sh`. There is no out-of-band
`aws secretsmanager create-secret` / `put-secret-value` step — a fresh
environment is fully provisioned by the normal bootstrap → `terraform apply`
flow, same as every other secret in the stack.

### Dev Box

| Secret Name | Contains |
|-------------|----------|
| `shifter-dev-box-admin-password` | Windows Administrator password (auto-generated) |

## GCP Secret Manager

`gcp-dev` stages parallel runtime secret bundles with the same shapes the portal
already expects at startup:

| Secret Name | Contains |
|-------------|----------|
| `shifter-gcp-dev-app` | Django `SECRET_KEY`, field encryption key |
| `shifter-gcp-dev-db` | Database connection JSON bundle |
| `shifter-gcp-dev-guacamole-db` | Guacamole PostgreSQL connection JSON bundle |
| `shifter-gcp-dev-guacamole-json-auth` | Guacamole JSON auth signing key |

Current rollout behavior:

- `shifter-gcp-dev-app` and `shifter-gcp-dev-db` are seeded by Terraform for the first deployable control-plane slice
- `shifter-gcp-dev-guacamole-db` and `shifter-gcp-dev-guacamole-json-auth` are now seeded by Terraform and synced into the `guacamole-runtime` Kubernetes Secret during deploy
- Identity Platform is provisioned by Terraform for the secure GCP portal login path
- The first GCP operator is seeded by bootstrap using `GCP_BOOTSTRAP_ADMIN_EMAIL` / `GCP_BOOTSTRAP_ADMIN_PASSWORD` (or an interactive prompt)
- Bootstrap operator elevation is runtime-configured with `PLATFORM_BOOTSTRAP_STAFF_EMAILS` / `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS`; these values must stay out of committed source
- The same `PLATFORM_BOOTSTRAP_STAFF_EMAILS` / `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS` contract is applied by the AWS/Cognito OIDC backend and the GCP Identity Platform backend on user login. These settings identify which authenticated users receive Django `is_staff` / `is_superuser`; they are not Django passwords and do not bypass the configured identity provider.
- GCP corporate users authenticate in the browser through Identity Platform's FirebaseUI/SDK flow. Django only accepts verified Google identity tokens and creates the application session after email-verification and MFA checks pass.
- The GCP bootstrap path now assumes the secure portal posture. It no longer preserves the old debug-auth fallback when hostname/TLS settings are missing
- The operational dependency chain is now explicit:
  - `public_hostname` must be configured
  - managed TLS must be enabled
  - Identity Platform must be provisioned successfully
  - the public DNS record must point at the GKE ingress IP so the managed certificate can become active

## What's NOT a Secret

These are configuration, not secrets, and live in committed tfvars:

- AWS region
- Instance types
- AMI IDs
- S3 bucket names
- VPC CIDRs
- Domain names
- Feature flags

**Rule**: If it doesn't grant access or authenticate, it's config, not a secret.

## Adding a New Secret

### GitHub Secret

1. Go to Settings > Secrets and variables > Actions
2. Click "New repository secret"
3. Name it following existing conventions
4. Reference in workflow: `${{ secrets.SECRET_NAME }}`

### AWS Secrets Manager

1. Create via Terraform (preferred):
```hcl
resource "aws_secretsmanager_secret" "my_secret" {
  name = "shifter-${var.environment}-my-secret"
}
```

2. Or via CLI:
```bash
aws secretsmanager create-secret \
  --name "shifter-dev-my-secret" \
  --secret-string '{"key": "value"}' \
  --profile $PANW_SHIFTER_DEV_PROFILE
```

3. Grant access via IAM policy in Terraform
4. Access in code via boto3 or environment variable injection

## Rotating Secrets

### Database Password
1. Update in Secrets Manager
2. Restart portal container (picks up new value)

### Django SECRET_KEY
1. Update in Secrets Manager
2. Restart portal (existing sessions invalidated)

### Cognito Client Secret
1. Rotate in Cognito console
2. Update in Secrets Manager
3. Restart portal

### VM guest passwords (per-instance)

Range guest desktop / RDP passwords are unique per instance. They are
**not** stored in the platform secret bundles, **not** carried as
environment variables, and **not** baked into AMIs. The password value
**never appears in EC2 user_data, IMDS, Terraform-rendered cloud-init
manifests, or the guest's process argv**.

The lifecycle aligns with the documented best practice for AWS Systems
Manager Parameter Store + Run Command (and the GCP equivalent: control-
plane-pushes-after-boot via the per-instance SSH identity-brokered
channel). See `docs/architecture/vm-guest-credential-preflight-762.md`.

#### Lifecycle

1. **Generate**: the range Terraform module (AWS) and
   `gdc_vmruntime_assets._ensure_rdp_password_secret` (GCP) generate a
   per-instance random password with all four character classes (upper,
   lower, digit, shell-safe punctuation) enforced.
2. **Store**: the value is persisted in the cloud's secret manager:
   - AWS: `arn:aws:secretsmanager:<region>:<account>:secret:shifter/<env>/range/<range_id>/<role>-<uuid8>-rdp-password`
   - GCP: `projects/<project>/secrets/shifter-<env>-range-<range_id>-<role>-<token>-rdp-password`
3. **Reference, don't render**: the secret ARN / resource path flows
   into `engine_instance.state.rdp_password_secret_arn` and
   `Range.provisioned_instances[].rdp_password_secret_arn`. The
   *value* never lands in EC2 user_data, GDC VM Runtime
   cloud-init data, or Terraform-rendered scripts.
4. **Push at provisioning time**: after the instance comes up and the
   per-instance SSH key is in `authorized_keys` /
   `administrators_authorized_keys`, the engine provisioner runs
   `SetLocalPasswordPlan` via `SetupOrchestrator`:
   - Linux (kali, ubuntu): the password is piped through `chpasswd`
     stdin — never as a `chpasswd` argv.
   - Windows victim: `Set-LocalUser -Password (ConvertTo-SecureString …)` —
     never as a `net user` argv.
   - `SetupOrchestrator.SENSITIVE_CONTEXT_KEY_PARTS` masks the value
     in captured stdout/stderr because the context key is
     `rdp_password`.
5. **Resolve at access time**: the portal's
   `engine.services._resolve_non_dc_rdp_password` reads the per-
   instance secret reference from `Range.provisioned_instances` and
   fetches the value via `engine.secrets.get_rdp_password` →
   `shared.cloud.get_secrets_store().get_secret()`. If the fetch fails
   (deleted secret, IAM regression), the portal raises a
   non-sensitive `ValueError` that the Mission Control RDP view maps
   to HTTP 400 — same envelope as a missing reference.

#### DC role

The DC role keeps the deployment-scoped `DC_DOMAIN_PASSWORD` contract
documented below — a DC host's local Administrator account *is* the
domain Administrator account, so per-instance rotation is handled
through DC promotion rather than the per-instance secret.

#### Residual state exposure

The generated `random_password.result` (AWS) and the
`add_secret_version` payload (GCP) appear in Terraform / provisioner-
side memory at apply time and in the Terraform state object for the
AWS path, the same as the existing per-instance SSH-key precedent
(`tls_private_key.instance` and `aws_secretsmanager_secret_version.ssh_key`).
Terraform state lives in the S3 backend with bucket-level encryption
and least-privilege IAM access; this is the established mitigation.
Eliminating state exposure entirely would require external secret
generation (e.g., a Lambda invoking `aws secretsmanager create-secret`)
and is a separate workstream.

#### Residual SSM Run Command body exposure (AWS)

For the AWS push path, the rendered `SetLocalPasswordPlan` script body
contains the per-instance password (Linux: in a `chpasswd` here-doc;
Windows: as the `$Password` variable assigned to `ConvertTo-SecureString`).
SSM Run Command persists the command body in CloudWatch Logs / S3
output (if configured) and in the `GetCommandInvocation` API record.
This is the same residual exposure as the pre-existing `DCSetupPlan`
and `DomainJoinPlan`, which also render `DC_DOMAIN_PASSWORD` into
their script bodies. The established mitigations are:

- `ssm:GetCommandInvocation` and `ssm:ListCommands` are scoped to
  the engine-provisioner ECS task role and platform administrators;
  range guests and portal users never have this grant.
- `SetupOrchestrator.SENSITIVE_CONTEXT_KEY_PARTS` masks the value in
  our own captured stdout/stderr (the orchestrator-side log redaction).
- Run Command results in the AWS-managed S3 bucket are server-side
  encrypted with the bucket's KMS key.

The architecturally cleanest fix would be SSM SecureString parameter
substitution (`{{ssm-secure:/path/to/secret}}`), which resolves the
value inside the SSM agent on the target without recording the value
in the command body. That requires migrating the secret store from
Secrets Manager to SSM Parameter Store SecureString (or maintaining
both) and is a separate workstream tracked outside of #762.

#### Rotation

Per-instance rotation is achieved by destroying and re-provisioning
the range; the Terraform `random_password` regenerates, the new value
replaces the previous secret version, and `SetLocalPasswordPlan` pushes
it on the next provision. Image rebuilds (Packer) do **not** rotate
live credentials — they only refresh the bootstrap scripts shipped on
first boot.

### Domain Controller Administrator Password

The portal Django container reads `DC_DOMAIN_PASSWORD` once at startup
(`entrypoint.sh`) and caches it in the process environment, so a Secrets
Manager update does not refresh a running portal. The engine provisioner ECS
task, by contrast, has the value injected by ECS at each task launch via the
task definition's `secrets = [...]` block, so range provisions/joins after the
rotation pick up the new value without a task-definition redeploy.

1. Regenerate the value and re-seed the secret with one Terraform apply:
   ```bash
   terraform apply -replace='module.engine_provisioner.random_password.dc_domain_password'
   ```
   (Terraform regenerates `random_password.dc_domain_password` and updates
   `aws_secretsmanager_secret_version.dc_domain_password`.)
2. Restart the portal containers so the new value is loaded:
   ```bash
   docker restart portal worker-engine worker-cms worker-mc ctf-scheduler
   ```
   (or terminate the portal EC2 and let the ASG relaunch).
3. Re-provision any ranges whose DC was promoted with the old value so the live
   domain credential matches the secret again — existing ranges keep the old
   password until they are re-provisioned. No engine provisioner task-definition
   redeploy is required; the next ECS task launch reads the rotated value.

### GitHub OIDC Role
Role ARN doesn't change. Trust policy updates are in `platform/terraform/global/iam/`.

### GCP Workload Identity Federation
The provider resource and target service account stay stable. Rotate or tighten
permissions in GCP IAM without changing the GitHub workflow contract unless the
provider or service account identity itself changes.

## Accessing Secrets Locally

For local development, you can retrieve secrets:

```bash
# Get a secret value
aws secretsmanager get-secret-value \
  --secret-id shifter-dev-portal-db-credentials \
  --profile $PANW_SHIFTER_DEV_PROFILE \
  --query SecretString --output text | jq .

# Use in environment
export DB_PASSWORD=$(aws secretsmanager get-secret-value \
  --secret-id shifter-dev-portal-db-credentials \
  --profile $PANW_SHIFTER_DEV_PROFILE \
  --query SecretString --output text | jq -r .password)
```

## Security Checklist

- [ ] Secret not in any committed file
- [ ] Secret not in shell history (`use read -s` for input)
- [ ] Appropriate IAM policy restricts access
- [ ] Rotation procedure documented
- [ ] Dev and prod use different secrets
