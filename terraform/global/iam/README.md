# Global IAM

## Purpose

Global IAM provides GitHub Actions authentication and authorization to AWS via OIDC federation. No static credentials are stored in GitHub.

## Architecture

### OIDC Federation

GitHub Actions authenticates to AWS using OpenID Connect:

1. GitHub Actions requests a JWT from GitHub's OIDC provider
2. AWS validates the JWT against the configured OIDC provider
3. AWS issues temporary credentials via STS AssumeRoleWithWebIdentity
4. Credentials are scoped to the github-actions-shifter role

### Trust Policy

The IAM role trusts GitHub's OIDC provider with conditions:
- Audience must be `sts.amazonaws.com`
- Subject must match `repo:Brad-Edwards/shifter:*` (any branch/tag/workflow)

This prevents other GitHub repositories from assuming the role.

### Permissions Model

Permissions are split across multiple IAM policies to avoid the 6,144 character managed policy size limit:

- **Core Infrastructure**: ECR, S3 state, DynamoDB locking, user storage
- **VPC Networking**: VPC, subnets, routing, security groups, gateways
- **EC2 Instances**: Instance lifecycle, volumes, key pairs
- **ELB and ACM**: Load balancers, SSL certificates
- **IAM Scoped**: Role and instance profile management (scoped to account)
- **Lambda and Step Functions**: Serverless compute, state machines, CloudWatch
- **RDS**: Database instances, subnet groups, parameter groups
- **Secrets and KMS**: Secrets Manager, encryption keys
- **SSM and Cognito**: Systems Manager, user pools

All policies use least-privilege scoping:
- Resources limited by ARN patterns (e.g., `shifter-*`)
- Region and account ID constraints where applicable
- Service-specific actions only

## Components

| Resource | Purpose | Notes |
|----------|---------|-------|
| OIDC Provider | GitHub token validation | Thumbprints for GitHub's signing certs |
| IAM Role | GitHub Actions principal | Assumes via web identity, no static keys |
| IAM Policies | Permission boundaries | Split to avoid size limits |

## Usage

### Prerequisites

- AWS account with admin access for initial setup
- GitHub repository with Actions enabled
- Terraform >= 1.0

### Deploy

Global IAM is deployed once during initial setup and rarely changes. Manual deployment from terraform/global/iam directory using standard terraform workflow.

### Configuration

Variables:
- `aws_region`: AWS region (default: us-east-2)
- `github_org`: GitHub organization (default: Brad-Edwards)
- `github_repo`: GitHub repository (default: shifter)

### Outputs

- `github_actions_role_arn`: IAM role ARN to configure in GitHub secrets as `AWS_ROLE_ARN`
- `oidc_provider_arn`: OIDC provider ARN for reference

### GitHub Secrets Setup

After deployment, configure GitHub repository secrets:

1. Add `AWS_ROLE_ARN` with the role ARN from terraform output
2. Add `AWS_REGION` with the deployment region

Workflows use `aws-actions/configure-aws-credentials` to assume the role.

## Security Considerations

### OIDC Thumbprints

Thumbprints verify GitHub's signing certificates. Current values are valid as of deployment. GitHub rotates certificates periodically; update thumbprints if authentication fails after cert rotation.

### Scope Restrictions

Policies are scoped to prevent:
- Cross-account access (account ID in ARNs)
- Cross-region access (region in ARNs where supported)
- Non-shifter resources (name patterns in ARNs)

### PassRole Permission

The `iam:PassRole` permission allows terraform to assign IAM roles to AWS services (EC2, Lambda, etc.). This is required for instance profiles and execution roles but is scoped to the same account.

### Service-Linked Roles

Permission to create service-linked roles is required for some AWS services (e.g., ELB, RDS). These are created by AWS services themselves and cannot be avoided.

## Maintenance

### Adding Permissions

When adding new AWS resources:

1. Identify the required IAM actions
2. Add to appropriate policy by resource type
3. Use least-privilege scoping (ARN patterns, conditions)
4. Test in target environment before deployment
5. Deploy to global IAM before dependent infrastructure

### Rotating OIDC Thumbprints

If GitHub rotates certificates:

1. Obtain new thumbprints from GitHub's OIDC endpoint
2. Update thumbprint list in global IAM configuration
3. Apply changes with terraform

### Auditing Access

Review CloudTrail logs for actions taken by the github-actions-shifter role. All API calls are logged with source identity.

## Workflow Integration

All infrastructure workflows use this IAM role via the `aws-actions/configure-aws-credentials` action with the role ARN and region from GitHub secrets. No long-lived credentials in GitHub secrets. Credentials auto-expire after workflow completion.

## Dependencies

Global IAM has no dependencies on other Shifter components. It must be deployed first before any infrastructure workflows can run.

All other terraform deployments depend on this IAM role for authentication.
