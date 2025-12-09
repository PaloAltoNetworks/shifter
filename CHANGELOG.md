# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.7] - 2025-12-09

### Added
- Dashboard Range launch flow with live status polling
- Range API endpoints (status, launch, cancel, destroy, callback)
- Range model status fields (pending, provisioning, ready, paused, resuming, destroying, destroyed, failed)
- Stub provisioner service with HMAC-signed callback tokens
- Client-side DashboardManager for state management
- State transition validation to prevent callback replay attacks
- Range API tests (19 new tests)

## [0.2.6] - 2025-12-08

### Fixed
- Upload lock clears on page navigation/error (beforeunload + 30s timeout fallback)

## [0.2.5] - 2025-12-08

### Added
- 2GB file upload via presigned S3 URLs with progress indicator
- 5GB per-user storage quota
- Upload cancel/abort support
- S3 CORS configuration for browser uploads
- S3 lifecycle rule for orphan cleanup

## [0.2.4] - 2025-12-08

### Fixed
- Logout now clears Cognito session (redirects to Cognito /logout endpoint)
- Local dev logout uses dev_logout instead of OIDC logout

## [0.2.3] - 2025-12-08

### Fixed
- Agent uploads failing: container now uses EC2 instance role via IMDSv2

### Removed
- Static IAM user credentials for portal container

## [0.2.2] - 2025-12-08

### Added
- Agent upload to S3 with magic byte validation
- File type validation (.msi, .zip, .tar.gz, .tgz, .deb, .rpm)
- Agent delete with S3 cleanup
- S3 bucket env var in deploy workflow

## [0.2.1] - 2025-12-08

### Added
- Mission Control data models (OperatingSystem, UserProfile, AgentConfig, Range, ActivityLog)
- Django admin registration for all models
- UserProfile auto-creation signal
- Model unit tests (21 tests, 100% coverage)

## [0.2.0] - 2025-12-08

### Added
- Mission Control UI shell (Dashboard, Agents, History, Settings, Help)
- Dev auth bypass for local testing
- User stories: Help, Language, Notifications

## [0.1.19] - 2025-12-08

### Changed
- Updated license to proprietary
- Block access to /admin from public internet

## [0.1.18] - 2025-12-08

### Changed
- Improved portal coming soon page design

## [0.1.17] - 2025-12-08

### Fixed
- Insecure TLS config in MCP HTTP client (removed global NODE_TLS_REJECT_UNAUTHORIZED)
- Portal deploy/infra workflow race condition (workflow_run trigger + concurrency)

### Security
- Upgraded @modelcontextprotocol/sdk to 1.24.3 (CVE-2025-66414 DNS rebinding fix)

## [0.1.16] - 2025-12-08

### Changed
- README update

## [0.1.15] - 2025-12-07

### Added
- Landing page at / to prevent redirect loop after OIDC auth

## [0.1.14] - 2025-12-07

### Fixed
- Cognito secret retrieval from Secrets Manager (issuer -> issuer_url key)

## [0.1.13] - 2025-12-07

### Added
- S3 user storage module for file uploads (agents, etc.)
- GitHub Actions IAM permissions for S3 bucket management

## [0.1.12] - 2025-12-07

### Added
- Range VPC module - stable VPC, IGW, route table
- Range environment config
- Range infrastructure workflow
- Range infrastructure documentation

## [0.1.11] - 2025-12-07

### Added
- Cognito Terraform module (user pool, client, hosted UI domain)
- Pre-signup Lambda for email domain restriction
- Auth architecture docs
- Wire Cognito into portal environment
- EC2 module accepts list of secret ARNs
- IAM permissions for Cognito and Lambda
- Django OIDC integration (mozilla-django-oidc)
- Entrypoint fetches Cognito secrets from Secrets Manager
- Deploy workflow passes COGNITO_SECRET_ARN to container

## [0.1.10] - 2025-12-07

### Fixed
- Hardcoded domain in Django ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS replaced with domain from tfvars secret

## [0.1.9] - 2025-12-07

### Fixed
- IAM permissions for SSM SendCommandToInstances
- Staticfiles directory permission error in container

## [0.1.13] - 2025-12-07

### Added
- S3 user storage module for file uploads (agents, etc.)
- GitHub Actions IAM permissions for S3 bucket management

## [0.1.8] - 2025-12-07

### Added
- Django portal Docker setup (multi-stage Dockerfile with uv)
- Container entrypoint with DB wait, migrations, gunicorn
- docker-compose.yml for local dev with Postgres
- Makefile with dev commands (up, down, build, logs, shell, migrate, init)
- GitHub Actions workflow for portal build, ECR push, SSM deploy
- Portal dev documentation 
- Secrets management: IAM user for prod, Secrets Manager for DB + app secrets

### Changed
- Architecture docs updated with portal deployment pipeline
- GitHub OIDC role gets SSM permissions for deployments

## [0.1.7] - 2025-12-07

### Added
- Portal EC2 module (Docker host, SSM access, ECR/Secrets Manager IAM)
- Portal ALB module (ACM certificate, HTTPS listener, target group)
- Environment wiring with terraform_remote_state for ECR
- IAM permissions for EC2, ELB, ACM
- Security documentation
- Ethics documentation
- Disclaimer in README

### Changed
- Architecture docs updated for EC2+ALB (was ECS)
- ECR authentication via credential helper (replaces manual docker login)

### Security
- IMDSv2 enforced on EC2 (SSRF mitigation)
- ALB drops invalid HTTP headers
- ACM certificate validation with 45m timeout

## [0.1.6] - 2025-12-05

### Fixed
- Missing IAM permissions for ec2:ModifySubnetAttribute and iam:CreateServiceLinkedRole (RDS)

## [0.1.5] - 2025-12-05

### Added
- Portal VPC module (public/private subnets, NAT gateway)
- Portal RDS module (PostgreSQL, Secrets Manager credentials)
- Namespaced tfvars sync script (`TF_VARS_{ENV}_{COMPONENT}`)
- IAM permissions for VPC, RDS, Secrets Manager, KMS

## [0.1.4] - 2025-12-05

### Added
- Terraform foundation infrastructure (ECR module, global IAM, environment structure)
- GitHub Actions OIDC authentication for AWS
- CI/CD workflow for infrastructure deployment
- Version bump script

## [0.1.3] - 2025-12-05

### Added
- MkDocs with Material theme
- Documentation site (architecture, setup, API reference)
- GitHub Actions workflow for automatic GitHub Pages deployment
- Mermaid.js diagrams in architecture docs

## [0.1.2] - 2025-12-04

### Added

- Image assets for docs

### Changed
- Updated CLAUDE.md to reflect new architecture
- Removed unused files from .gitignore
- Only run mcp tests on code change

## [0.1.1] - 2025-12-04

### Added
- SonarCloud integration
- Build and test workflow
- Quality gate badge to README

### Fixed
- npm version mismatch

### Changed
- Upgraded vitest from 1.x to 4.x (required code changes to test files due to breaking changes)
## [0.1.0] - 2025-12-04

### Added
- Initial Shifter architecture for self-service cyber range platform
- Core MCP library (`mcp/aptl-mcp-common`) with SSH session management
- Reference MCP server (`mcp/mcp-red`) as template for new MCPs
- SonarCloud integration with automated code quality scanning
- Test coverage reporting via vitest with lcov output

### Changed
- Forked from APTL (Advanced Purple Team Lab) with new direction

### Removed
- All Docker/Wazuh infrastructure (replaced by XDR/XSIAM integration)
- Container definitions (kali, victim, gaming-api, minetest, minecraft, reverse)
- CTF scenarios (will be AI-generated dynamically)
- Local deployment scripts

