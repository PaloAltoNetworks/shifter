# Security

## Network

- EC2 and RDS in private subnets, no direct internet access
- ALB in public subnets, only component with internet exposure
- ALB security group: inbound 443/80 only
- EC2 security group: inbound 8000 from ALB security group only
- RDS security group: inbound 5432 from EC2 security group only
- Egress via NAT Gateway

## Encryption

- HTTPS enforced via ALB (ACM certificate)
- HTTP redirects to HTTPS
- RDS storage encrypted at rest (AWS managed key)
- ALB drops invalid HTTP headers (`drop_invalid_header_fields = true`)

## IAM

- GitHub Actions uses OIDC federation, no static credentials
- IAM role scoped to `shifter-*` resources
- EC2 instance profile with least-privilege policies:
  - ECR pull (specific repository)
  - Secrets Manager read (specific secret ARN)
  - SSM Session Manager access

## Instance Hardening

- IMDSv2 required (mitigates SSRF attacks against metadata service)
- ECR credential helper (no stored Docker tokens)
- SSM Session Manager for access (no SSH key management)

## Secrets

- RDS credentials in Secrets Manager, auto-generated
- Terraform variables in GitHub Secrets, synced via `sync-tfvars.sh`
- `.tfvars` files gitignored

## Not Yet Implemented

- WAF on ALB
- ALB access logging
- Cloudflare proxy with IP allowlisting
- VPC Flow Logs
