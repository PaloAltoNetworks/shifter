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
| `shifter-gcp-dev-oidc` | OIDC client ID, client secret, issuer URL, auth domain |
| `shifter-gcp-dev-guacamole-json-auth` | Guacamole JSON auth signing key |

Current rollout behavior:

- `shifter-gcp-dev-app` and `shifter-gcp-dev-db` are seeded by Terraform for the first deployable control-plane slice
- `shifter-gcp-dev-guacamole-db` and `shifter-gcp-dev-guacamole-json-auth` are now seeded by Terraform and synced into the `guacamole-runtime` Kubernetes Secret during deploy
- `shifter-gcp-dev-oidc` still needs to be populated before the non-debug portal auth path is enabled
- The `gcp-dev` deploy workflow only exports `OIDC_SECRET_ID` into the portal runtime when all of these conditions hold: `public_hostname` is set, managed TLS is enabled, the OIDC secret has a readable latest version, and the GKE managed certificate reaches `Active`
- If any of those checks fail, the workflow intentionally keeps `DJANGO_DEBUG=true` and insecure cookies disabled so `gcp-dev` remains reachable through the debug-auth path instead of failing hard during startup

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
