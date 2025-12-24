# Secrets Management

Where secrets live and how to manage them.

## Principles

1. **Never in code** - No secrets in source files or environment configs
2. **GitHub Secrets for CI/CD** - OIDC role ARNs only
3. **AWS Secrets Manager for runtime** - Application secrets at runtime
4. **Explicit, not default** - No silent fallbacks; fail if secret missing
5. **tfvars are config, not secrets** - Committed to repo, no sensitive values

## GitHub Secrets

These must be configured in repository Settings > Secrets and variables > Actions.

| Secret | Purpose |
|--------|---------|
| `AWS_ROLE_ARN` | GitHub Actions IAM role for **prod** (OIDC) |
| `AWS_ROLE_ARN_DEV` | GitHub Actions IAM role for **dev** (OIDC) |

These are IAM role ARNs for OIDC federation. No static access keys.

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
Role ARN doesn't change. Trust policy updates are in `terraform/global/iam/`.

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
