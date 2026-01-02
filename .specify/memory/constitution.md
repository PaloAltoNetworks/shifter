<!--
Sync Impact Report
==================
Version change: 0.0.0 → 1.2.0 (MINOR - added Speed to Value, customer-facing polish, revised Simplicity)
Modified principles:
  - V. Simplicity First → V. Simplicity & Pragmatism (removed single-process constraint)
Added sections:
  - Core Principles (6 principles, added Speed to Value)
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

### I. Speed to Value

User time is worth $100-200/hr. Current demo setup can take a day or more. Every
feature MUST minimize time from login to productive use.

- Self-service by default; users MUST NOT need admin intervention for standard operations
- Turnkey experience: users cannot install tools locally on work laptops
- Pre-built scenarios and templates MUST be available for common use cases
- Provisioning status MUST be visible in real-time (WebSocket, not polling)
- Async operations and multi-process execution where needed for responsiveness
- Customer-facing polish: UI MUST be consistent with PANW Cortex product suite aesthetics

### II. Safety & Isolation

Ranges MUST be network-isolated. All infrastructure provisioned by the Engine runs in a
dedicated Range VPC with egress filtering via AWS Network Firewall. No direct internet
ingress to range instances is permitted. VPC peering exists only for terminal access
from the Portal VPC.

- Range instances MUST NOT have public IP addresses
- Egress MUST be filtered through Network Firewall with domain-based rules
- SSH access MUST route through authenticated WebSocket consumers in Mission Control
- MFA MUST be enforced for all user authentication (Cognito TOTP)

### III. Human Oversight

Human oversight is required for all scenario execution. AI-driven attack capabilities
exist to provide realistic training, but all actions MUST be logged and auditable.

- All AI actions MUST be logged via `management.services.log_activity()`
- Users MUST explicitly trigger range provisioning, destruction, and scenario execution
- No autonomous attack execution without user initiation
- Activity logs MUST include user, action, timestamp, and relevant metadata

### IV. Domain-Driven Design

The platform is organized into four bounded contexts, each a Django app with distinct
responsibilities. Cross-domain communication uses Python service interfaces, not HTTP.

| Domain | App | Responsibility |
|--------|-----|----------------|
| Mission Control | `mission_control` | Presentation layer. Views, API endpoints, WebSocket consumers. |
| Shifter Engine | `engine` | Infrastructure lifecycle. Range provisioning, NGFW operations. |
| Shifter CMS | `cms` | Content management. Assets, credentials, scenarios. |
| Shifter Management | `management` | Platform administration. Audit logging, user management. |

- Domains MUST expose functionality via service modules (`<app>.services`)
- Views MUST NOT contain business logic; they handle HTTP concerns only
- Cross-domain foreign keys are permitted; business logic via service calls
- Status updates MUST use Redis pub/sub channels, not database polling

### V. Infrastructure as Code

All AWS infrastructure MUST be defined in Terraform. Manual console changes are
prohibited except for initial bootstrap operations.

- Terraform modules in `platform/terraform/modules/` for reusable components
- Environment configs in `platform/terraform/environments/{dev,prod}/`
- State stored in S3 with DynamoDB locking
- OIDC federation for CI/CD authentication; no long-lived AWS credentials
- Range subnets created at runtime by Pulumi Provisioner (Engine), not Terraform

### VI. Simplicity & Pragmatism

Keep things simple. Don't reinvent the wheel. Use proven, solid technologies.

- YAGNI: Do not build features that are not immediately required
- Prefer Django conventions over custom abstractions
- Use multi-process/async where needed for performance and responsiveness
- Question existence: Does this file/abstraction need to exist? Is it duplicative?

## Platform Constraints

Shifter is an enterprise cyber range platform in the broadest sense. It is an internal
enablement tool, not a product—but it is used in front of customers and MUST be polished.

- Target users: PANW SecOps Domain Consultants who need turnkey, self-service access
- Use cases: XDR/XSIAM demos, attack scenario testing, purple/red/blue team exercises
- Customer-facing: UI/UX MUST be professional and consistent with Cortex product suite
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

### Agent Conduct

AI agents working on this codebase MUST act as a collaborative principal engineer:

- Do exactly what is requested, not some interpreted variation
- Ask before making changes beyond what was explicitly requested
- Never add "helpful" extras, refactors, or improvements unless you get explicit permission FIRST
- Think before doing: understand context and the bigger picture before starting any task
- Flag problems: surface oddities, inconsistencies, or subtle breakage rather than skating past
- Stop and discuss with the user if something doesn't make sense
- Never make architectural decisions for the user; get explicit permission
- Follow the user's lead; do not jump ahead on tasks
- NEVER run git commands (add, commit, push, PR) unless explicitly instructed by the user
- MUST follow the TDD workflow in `.claude/skills/tdd-plan/SKILL.md` for all implementation work

### Compliance

Code reviews MUST verify alignment with these principles. Use `.cursor/rules` and
agent guidance files for runtime development guidance.

**Version**: 1.2.0 | **Ratified**: TODO(RATIFICATION_DATE): original adoption date unknown | **Last Amended**: 2025-01-01
