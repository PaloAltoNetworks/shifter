# Security

## Architecture Overview

```
                              INTERNET
                                  │
                    ┌─────────────┴─────────────┐
                    │                           │
                    ▼                           ▼
          ┌─────────────────┐         ┌─────────────────┐
          │   PORTAL VPC    │         │    RANGE VPC    │
          │  (10.0.0.0/16)  │         │  (10.1.0.0/16)  │
          │                 │         │                 │
          │  ┌───────────┐  │  VPC    │  ┌───────────┐  │
          │  │ ALB + WAF │  │ Peering │  │  AWS NET  │  │
          │  └─────┬─────┘  │◄───────►│  │ FIREWALL  │  │
          │        │        │ SSH only│  └─────┬─────┘  │
          │  ┌─────▼─────┐  │         │        │        │
          │  │  Django   │  │         │  ┌─────▼─────┐  │
          │  │   EC2     │  │         │  │    NAT    │  │
          │  └─────┬─────┘  │         │  └─────┬─────┘  │
          │        │        │         │        │        │
          │  ┌─────▼─────┐  │         │  User Subnets   │
          │  │    RDS    │  │         │  ┌─────┬─────┐  │
          │  └───────────┘  │         │  │Kali │Victim│ │
          └─────────────────┘         │  └─────┴─────┘  │
                                      └─────────────────┘
```

## Web Application Firewall (WAF)

AWS WAFv2 protects the Portal ALB with managed rule sets:

| Rule | Purpose |
|------|---------|
| `RateLimitRule` | 2000 requests/5 min per IP |
| `AWSManagedRulesAmazonIpReputationList` | Known malicious IPs |
| `AWSManagedRulesKnownBadInputsRuleSet` | Log4Shell, SSRF, etc. |
| `AWSManagedRulesCommonRuleSet` | OWASP Top 10 |

WAF is enabled by default in both dev and prod environments.

## Network

### Portal VPC

- EC2 and RDS in private subnets, no direct internet access
- ALB in public subnets, only component with internet exposure
- ALB security group: inbound 443/80 only
- EC2 security group: inbound 8000 from ALB security group only
- RDS security group: inbound 5432 from EC2 security group only
- Egress via NAT Gateway

### Range VPC

Separate VPC (`10.1.0.0/16`) for attack lab environments with egress filtering.

**Network Firewall:**

AWS Network Firewall inspects all egress traffic with domain-based allowlists:

| Instance | Allowed Egress | Blocked |
|----------|---------------|---------|
| Kali | VPC internal only | All internet access |
| Victim (Linux/Windows) | `.paloaltonetworks.com`, `.storage.googleapis.com` | Everything else |

Additional protections:
- **SNI bypass prevention**: Blocks TLS connections using IP addresses as SNI (prevents domain allowlist bypass)
- **Suricata rules**: Custom rules reject direct IP connections

Traffic flow: `User Subnet → Network Firewall → NAT Gateway → IGW → Internet`

**Security Groups:**

| SG | Ingress | Egress | Purpose |
|----|---------|--------|---------|
| Kali | SSH from Portal+Range VPC, ALL from Victim SG | VPC CIDR, DNS | Attack box |
| Victim | SSH from Portal+Range VPC, ALL from Kali SG | HTTPS, DNS | Target with XDR agent |
| DC | SSH from Portal+Range VPC, ALL from Kali SG, AD ports from Victim SG | HTTPS, DNS | Domain controller |

DC security group allows AD traffic (LDAP, Kerberos, DNS, SMB) from domain members.

**Design Decisions:**

- **Bidirectional Kali ↔ Victim traffic**: Required for reverse shells, C2 callbacks, and realistic attack scenarios
- **Kali locked down**: No external access—tools are pre-installed on AMI
- **Victim XDR-only egress**: Only domains required for XDR/XSIAM telemetry
- **Security group references**: Traffic rules use SG IDs, not CIDR blocks—prevents cross-user subnet attacks

**Isolation:**

- Each user gets their own `/24` subnet (starting at 10.1.1.0/24)
- 10.1.0.0/24 reserved for infrastructure (firewall, NAT subnets)
- Kali/Victim can only talk to each other within the same subnet
- No cross-subnet traffic possible (SG rules reference specific SGs, not VPC CIDR)

### VPC Peering

Portal VPC ↔ Range VPC peering enables browser-based SSH terminal access:

- Portal initiates peering connection
- Routes added to both VPCs' private route tables
- Traffic restricted to SSH (port 22) via security groups
- No direct internet path between VPCs

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
- Range SSH keys stored in Secrets Manager (per-range)
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

## Known Risks

| Risk | Severity | Notes |
|------|----------|-------|
| Range instances can enumerate SSM documents | Low | `ssm:GetDocument` in managed policy. Audit for secrets in docs. |

## Logging and Observability

Log aggregation requires `enable_log_aggregation = true` to activate:

| Log Type | Destination | Status |
|----------|-------------|--------|
| Application logs | CloudWatch → Firehose → S3 | Implemented |
| Cognito logs | CloudWatch → Firehose → S3 | Implemented |
| Pulumi Provisioner logs | CloudWatch → Firehose → S3 | Implemented |
| VPC Flow Logs | CloudWatch → Firehose → S3 | Implemented |
| RDS PostgreSQL logs | CloudWatch → Firehose → S3 | Implemented |
| ALB access logs | Direct to S3 | Implemented |
| WAF logs | Firehose → S3 | Implemented |
| Network Firewall logs | CloudWatch (ALERT + FLOW) | Implemented |

### XDR CloudTrail Integration

XDR ingests CloudTrail audit logs via a CloudFormation template from the Cortex console. This is separate from the application logs above.

| Component | Source | Purpose |
|-----------|--------|---------|
| CloudTrail | XDR CloudFormation | API audit logs (who did what in AWS) |
| App logs | Terraform log-aggregation | Internal debugging (what happened in Shifter) |

CloudFormation templates are in `cloudformation/{env}/` (environment-specific).

## Not Yet Implemented

- Cloudflare proxy with IP allowlisting
