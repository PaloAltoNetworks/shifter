# Security

## Network

### Portal VPC

- EC2 and RDS in private subnets, no direct internet access
- ALB in public subnets, only component with internet exposure
- ALB security group: inbound 443/80 only
- EC2 security group: inbound 8000 from ALB security group only
- RDS security group: inbound 5432 from EC2 security group only
- Egress via NAT Gateway

### Range VPC

Separate VPC (`10.1.0.0/16`) for attack lab environments.

**Security Groups:**

| SG | Ingress | Egress | Purpose |
|----|---------|--------|---------|
| Kali | SSH from VPC, ALL from Victim SG | ALL | Attack box |
| Victim | SSH from VPC, ALL from Kali SG | ALL | Target with XDR agent |

**Design Decisions:**

- **Bidirectional Kali ↔ Victim traffic**: Required for reverse shells, C2 callbacks, and realistic attack scenarios
- **Unrestricted egress**: Kali needs apt for tools; Victim needs internet for XDR agent callbacks
- **SSH from VPC CIDR**: Allows MCP/LibreChat to manage both instances
- **Security group references**: Traffic rules use SG IDs, not CIDR blocks—prevents cross-user subnet attacks

**Isolation:**

- Each user gets their own `/24` subnet
- Kali/Victim can only talk to each other within the same subnet
- No cross-subnet traffic possible (SG rules reference specific SGs, not VPC CIDR)
- Range VPC has no peering to Portal VPC

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
  - Secrets Manager read (specific secret ARNs)
  - S3 access (user storage bucket only)
  - SSM Session Manager access

## Instance Hardening

- IMDSv2 required (mitigates SSRF attacks against metadata service)
- IMDSv2 hop limit=2 (allows containers to access instance role credentials)
- ECR credential helper (no stored Docker tokens)
- SSM Session Manager for access (no SSH key management)
- Containers use instance role, no static IAM user credentials

## Admin Access

- Django `/admin` blocked at ALB level (returns 403)
- Admin access via SSM port forwarding only: `./scripts/portal-admin-tunnel.sh`
- Tunnel forwards localhost:9000 → EC2:8000, requires AWS credentials with SSM access

## Secrets

- RDS credentials in Secrets Manager, auto-generated
- Terraform variables in GitHub Secrets, synced via `sync-tfvars.sh`
- `.tfvars` files gitignored

## Authentication

AWS Cognito handles all authentication. Django is a relying party only.

**Why Cognito over Django auth:**

- SOC 2, ISO 27001, PCI DSS compliant
- No password storage in our DB
- MFA implementation is AWS's problem
- Brute force protection, rate limiting built-in
- Security patches handled by AWS

**Configuration:**

- User pool with email as username
- MFA required (TOTP)
- Email verification required
- Pre-signup Lambda enforces `@paloaltonetworks.com` domain
- External users: allowlist specific emails in Lambda

**Django integration:**

- OIDC callback validates Cognito JWT
- Creates minimal local User record (email only)
- No password fields, no reset flows, no MFA code
- `mozilla-django-oidc` for token handling

**Token flow:**

1. User hits protected route → redirect to Cognito hosted UI
2. User authenticates + MFA → Cognito redirects with auth code
3. Django exchanges code for tokens, validates JWT signature
4. Django creates session, stores user email from token claims

## Not Yet Implemented

- WAF on ALB
- ALB access logging
- Cloudflare proxy with IP allowlisting
- VPC Flow Logs
