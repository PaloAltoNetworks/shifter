# Bootstrap Scripts

AWS account bootstrap scripts for Shifter infrastructure.

## Usage

These are standalone bash scripts for bootstrapping a bare AWS account. They create:
- S3 bucket for Terraform state
- DynamoDB table for state locking  
- GitHub OIDC provider for keyless CI/CD
- IAM role with all required permissions

```bash
# Dev account
AWS_PROFILE=<your-dev-profile> ./scripts/bootstrap/dev.sh

# Prod account
AWS_PROFILE=<your-prod-profile> ./scripts/bootstrap/prod.sh
```

## Preferred: Use deploy.py

The `deploy.py` CLI provides an interactive walkthrough that includes bootstrap:

```bash
./scripts/deploy.py full --env prod
```

See `scripts/deploy.py --help` for all options.
