# Handoff Guide

Minimum requirements to transfer Shifter ownership to PANW.

## Repository Transfer

### GitHub Repository

1. Transfer repository ownership:
   ```bash
   # Current: Brad-Edwards/shifter
   # Target: paloaltonetworks/shifter (or appropriate PANW org)
   ```
   
   GitHub Settings → Danger Zone → Transfer ownership

2. Update repository references after transfer:
   - Update `repo_url` in `docs/mkdocs.yml`
   - Update GitHub Actions OIDC trust policy in `terraform/global/iam/main.tf`
   - Update any hardcoded references in documentation

### Team Access

Add PANW team members as repository collaborators:

- **Admin access**: Infrastructure/platform owners
- **Write access**: Developers and maintainers
- **Read access**: Security team, auditors

Configure via GitHub Settings → Collaborators and teams

## Authentication & Access

### SSO Integration

Current: AWS Cognito user pool with email-based authentication

Required for PANW integration:

1. **SAML integration** with PANW SSO (Okta/similar):
   - Configure Cognito user pool for SAML identity provider
   - Update pre-signup Lambda to validate PANW SSO attributes instead of email domain
   - Test SAML flow end-to-end

2. **Alternative**: Replace Cognito with PANW corporate identity provider
   - Requires Django authentication backend changes
   - Update `portal/config/settings.py` OIDC configuration
   - May require additional infrastructure changes

Current configuration: `terraform/modules/cognito/main.tf`

### Team Member Onboarding

Current process:

1. User must have `@paloaltonetworks.com` email
2. Self-registration via Cognito hosted UI
3. Email verification required
4. MFA setup required (TOTP)

Update for corporate SSO: Users provisioned via PANW identity management

## Security & Compliance

### InfoSec Assessment

Required security review areas:

1. **Network architecture**: VPC isolation, security groups, egress controls
   - See `docs/src/security.md` and `docs/src/architecture.md`

2. **Data protection**: RDS encryption, secrets management, PII handling
   - Credentials in AWS Secrets Manager
   - No customer data stored

3. **Authentication**: Current Cognito setup, planned SSO integration
   - MFA enforcement
   - Session management

4. **Vulnerability management**: Dependency scanning, code analysis
   - Current: SonarCloud integration (see badges in README)
   - May need PANW-approved tooling

5. **Incident response**: Logging, monitoring, audit trails
   - Current: CloudWatch logs
   - Integration with corp SIEM needed (see below)

### Required Security Changes

Based on InfoSec assessment, likely requirements:

- WAF on ALB (currently not implemented, see `docs/src/security.md`)
- VPC Flow Logs
- ALB access logging to S3
- Integration with PANW SIEM/logging infrastructure
- Code signing for container images
- Compliance with PANW data classification policies

## AWS Infrastructure

### Account Migration

Current: Deployed in Torq-owned AWS account

Migration options:

1. **Account transfer**: Transfer ownership of existing AWS account to PANW
   - Simplest path, no infrastructure changes
   - Requires AWS account ownership transfer process
   - Update billing, support plan

2. **Infrastructure migration**: Redeploy to PANW corporate AWS account
   - More complex, requires full redeployment
   - Benefits: Integration with corporate guardrails, OU policies
   - Steps:
     - Create new Terraform backend in target account
     - Update `terraform/*/backend.tf` files
     - Run `terraform apply` in target account
     - Migrate RDS data if preserving user data
     - Update DNS to point to new ALB
     - Decommission old infrastructure

Migration considerations:

- Current state backend: S3 bucket `shifter-infra-eedf1871-f634-4712-981a-5c6ba0738704`
- RDS database contains user accounts and range state
- ECR repositories contain portal container images
- No persistent user data stored beyond account info

### AWS Access

Required IAM permissions for operations team:

- Administrator access to Shifter resources (scoped to `shifter-*`)
- RDS database access for troubleshooting
- EC2 Systems Manager for portal access (no SSH)
- CloudWatch for logs and metrics
- Secrets Manager for credential rotation

Current: GitHub Actions uses OIDC federation (no static credentials)

## Operational Integration

### Support Ticketing

Required integrations:

- Link monitoring alerts to PANW ticketing system (ServiceNow/similar)
- Create runbooks for common issues
- Define escalation paths

Current monitoring: CloudWatch alarms (basic health checks)

### Observability

Current state:

- CloudWatch Logs for application logs
- CloudWatch Metrics for basic infrastructure metrics
- No distributed tracing
- No centralized log aggregation

Required for PANW integration:

1. **Logging**: Forward CloudWatch logs to corporate SIEM/log management
   - Options: Splunk, DataDog, Sumo Logic (whatever PANW uses)
   - Configure CloudWatch Logs subscription filters
   
2. **Metrics**: Integrate with corporate observability platform
   - Application metrics (API latency, error rates)
   - Infrastructure metrics (CPU, memory, network)
   - Cost tracking and attribution

3. **Alerting**: Route alerts to PANW on-call rotation
   - PagerDuty/similar integration
   - Define SLOs and alert thresholds

4. **Dashboards**: Create operational dashboards in corporate tools
   - Portal health
   - Range provisioning metrics
   - User activity

## Change Management

### Deployment Process

Current: GitHub Actions CI/CD

Post-handoff requirements:

- May need approval gates for production deployments
- Integration with PANW change management process
- Rollback procedures documented
- Maintenance windows coordinated with users

### Infrastructure as Code

All infrastructure in `terraform/` directory:

- Review and approve by PANW cloud architecture team
- May need to conform to PANW Terraform standards/modules
- State management in corporate-approved backend
- Secrets management aligned with PANW policies

## Documentation

### Current Documentation

- Technical docs: `docs/` (MkDocs)
- Deployment docs: `docs/src/setup.md`
- Architecture: `docs/src/architecture.md`
- Security: `docs/src/security.md`

### Required Updates

After handoff:

- Update contact information and escalation paths
- Add corporate runbooks and operational procedures
- Document integration with PANW systems
- Update brand guidelines (if needed)

## Handoff Checklist

Minimum steps to complete transfer:

- [ ] Transfer GitHub repository to PANW organization
- [ ] Add PANW team members as contributors
- [ ] Complete InfoSec security assessment
- [ ] Decide on AWS account strategy (transfer vs. migrate)
- [ ] If migrating AWS: Redeploy infrastructure to PANW account
- [ ] Integrate authentication with PANW SSO
- [ ] Configure logging to forward to corporate SIEM
- [ ] Set up monitoring alerts to page corporate on-call
- [ ] Create support ticketing integration
- [ ] Document operational runbooks for PANW support team
- [ ] Update all documentation with PANW contacts and procedures

## Open Questions

Items requiring decision before handoff:

1. Which PANW GitHub organization should own the repository?
2. What is the target AWS account (number/name)?
3. What is PANW's corporate SSO system and how should it integrate?
4. What observability/SIEM tools does PANW use?
5. What support ticketing system should alerts integrate with?
6. Are there PANW Terraform standards/modules that must be used?
7. What is the approval process for production deployments?
