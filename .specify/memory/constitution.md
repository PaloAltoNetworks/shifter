<!--
Sync Impact Report
==================
Version change: 0.0.0 → 1.0.0 (MAJOR - initial constitution)
Modified principles: N/A (first version)
Added sections:
  - Core Principles (5 principles)
  - Platform Constraints
  - Development Workflow
  - Governance
Removed sections: N/A
Templates requiring updates:
  - .specify/templates/plan-template.md ✅ (Constitution Check section compatible)
  - .specify/templates/spec-template.md ✅ (no changes needed)
  - .specify/templates/tasks-template.md ✅ (no changes needed)
Follow-up TODOs:
  - RATIFICATION_DATE: Original adoption date unknown
-->

# Shifter Constitution

## Core Principles

### I. Safety & Isolation

Ranges MUST be network-isolated. All infrastructure provisioned by the Engine runs in a
dedicated Range VPC with egress filtering via AWS Network Firewall. No direct internet
ingress to range instances is permitted. VPC peering exists only for terminal access
from the Portal VPC.

- Range instances MUST NOT have public IP addresses
- Egress MUST be filtered through Network Firewall with domain-based rules
- SSH access MUST route through authenticated WebSocket consumers in Mission Control
- MFA MUST be enforced for all user authentication (Cognito TOTP)

### II. Human Oversight

Human oversight is required for all scenario execution. AI-driven attack capabilities
exist to provide realistic training, but all actions MUST be logged and auditable.

- All AI actions MUST be logged via `management.services.log_activity()`
- Users MUST explicitly trigger range provisioning, destruction, and scenario execution
- No autonomous attack execution without user initiation
- Activity logs MUST include user, action, timestamp, and relevant metadata

### III. Domain-Driven Design

The platform is organized into four bounded contexts, each a Django app with distinct
responsibilities. Cross-domain communication uses Python service interfaces, not HTTP.

| Domain | App | Responsibility |
|--------|-----|----------------|
| Mission Control | `mission_control` | Presentation layer. DRF API, views, WebSocket consumers. |
| Shifter Engine | `engine` | Infrastructure lifecycle. Range provisioning, NGFW operations. |
| Shifter CMS | `cms` | Content management. Assets, credentials, scenarios. |
| Shifter Management | `management` | Platform administration. Audit logging, user management. |

- Domains MUST expose functionality via service modules (`<app>.services`)
- Views MUST NOT contain business logic; they handle HTTP concerns only
- Cross-domain foreign keys are permitted; business logic via service calls
- Status updates MUST use Redis pub/sub channels, not database polling

### IV. Infrastructure as Code

All AWS infrastructure MUST be defined in Terraform. Manual console changes are
prohibited except for initial bootstrap operations.

- Terraform modules in `platform/terraform/modules/` for reusable components
- Environment configs in `platform/terraform/environments/{dev,prod}/`
- State stored in S3 with DynamoDB locking
- OIDC federation for CI/CD authentication; no long-lived AWS credentials
- Range subnets created at runtime by Pulumi Provisioner (Engine), not Terraform

### V. Simplicity First

Start simple. Add complexity only when justified by concrete requirements, not
hypothetical future needs.

- YAGNI: Do not build features that are not immediately required
- Prefer Django conventions over custom abstractions
- Single process deployment; microservices complexity not warranted for current scale
- REST via DRF; no GraphQL or alternative API paradigms without justification

## Platform Constraints

Shifter is an internal enablement tool, not a product.

- Target users: Technical sellers demonstrating XDR/XSIAM capabilities
- NOT for product/stress testing PANW products or services
- NOT a replacement for BYOS, shared demo tenants, or official enablement tools
- Domain: `keplerops.com` (temporary; will migrate to `paloaltonetworks.com` if adopted)
- Identity: Cognito (temporary; will migrate to PANW SSO if adopted)

### Ethics

AI-driven attack capabilities exist because defenders need realistic exposure.
All attack tooling MUST be contained within isolated ranges with no external impact.

## Development Workflow

### CI/CD

GitHub Actions with self-hosted runners. Workflows trigger on file path changes.

| Branch | Behavior |
|--------|----------|
| `dev` | Deploy to dev environment |
| `main` | Deploy to prod environment |
| PR to `dev` | Plan and apply to dev |
| PR to `main` | Plan only (no apply) |

### Quality Gates

- Linting and security scanning via `_quality.yml`
- SonarCloud quality gate MUST pass
- All infrastructure changes require Terraform plan review

### Code Review

- PRs MUST verify compliance with this constitution
- Complexity additions MUST be justified in PR description
- Cross-domain changes MUST document service interface impacts

## Governance

This constitution supersedes all other development practices. Amendments require:

1. Documentation of the proposed change
2. Review and approval via PR
3. Migration plan for any breaking changes
4. Version increment following semantic versioning

### Versioning Policy

- **MAJOR**: Backward-incompatible principle removals or redefinitions
- **MINOR**: New principles added or existing guidance materially expanded
- **PATCH**: Clarifications, wording fixes, non-semantic refinements

### Compliance

All PRs and code reviews MUST verify alignment with these principles. Use
`.cursor/rules` and agent guidance files for runtime development guidance.

**Version**: 1.0.0 | **Ratified**: TODO(RATIFICATION_DATE): original adoption date unknown | **Last Amended**: 2025-12-31
