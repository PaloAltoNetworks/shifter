# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.1] - 2025-12-16

### Fixed
- XDR agent not installing on victim EC2 instances (#274)
  - Root cause: Network Firewall blocked S3 downloads (S3 domains not in allowlist)
  - Added S3 VPC Gateway Endpoint to Range VPC for direct S3 access
  - Added SSM-based agent verification before marking range as ready

### Added
- S3 Gateway Endpoint for Range VPC
  - Bypasses Network Firewall for S3 traffic
  - Optional endpoint policy to restrict access to agent bucket
- Agent verification step in provisioning workflow
  - New `verify_agent` Lambda checks installation via SSM RunCommand
  - Step Functions retry loop with 30s intervals (5 min max)
  - Ranges fail fast with descriptive error if agent install fails

## [0.7.0] - 2025-12-16

### Added
- Claude Code on Kali and Victim AMIs for AI-assisted penetration testing
  - Configured for Amazon Bedrock (no internet required)
  - Role-specific CLAUDE.md system prompts for each instance type
  - Kali: Authorized pentester role with subnet-only scope
  - Victim: Scenario setup assistant for vulnerable configurations
- Bedrock VPC endpoints (bedrock-runtime, sts) for Range VPC
- Bedrock IAM permissions for range instance role

### Changed
- Increased Portal EC2 instance to t3.large (from t3.micro) for WebSocket stability
- Increased Kali and Victim instances to t3.small for Claude Code memory requirements

## [0.6.0] - 2025-12-16

### Added
- Browser-based Terminal UI for SSH access to range instances (#267)
  - Side-by-side Kali and Victim terminal panes with xterm.js
  - WebSocket-based SSH via Django Channels
  - Terminal sidebar menu item with active range indicator
- VPC peering between Portal and Range VPCs for SSH connectivity
- Security group rules allowing SSH from Portal to range instances

### Changed
- Switched from Gunicorn (WSGI) to Daphne (ASGI) for WebSocket support

### Fixed
- Buttons should not have underline

## [0.5.4] - 2025-12-15

### Removed
- OpenWebUI/AgentChat infrastructure (#261)
  - Deleted agentchat Terraform modules and environments
  - Removed MCP-Shifter and OpenWebUI MCP wrapper code
  - Removed agentchat GitHub Actions workflows
  - Removed ECR repositories for openwebui and mcp-shifter
  - Removed Cognito agentchat client
  - Removed openwebui_db Secrets Manager secret
  - Removed agentchat documentation
  - Removed migrations for victim_mcp_user and kali_mcp_user rename
- Entire MCP directory (`mcp/`) including aptl-mcp-common and mcp-red

### Changed
- Architecture updated: Chat UI replaced with planned browser-based terminal (Django Channels)
- `chat_base_url` now optional in provisioner module (empty string allowed)
- Updated CLAUDE.md and architecture docs to reflect new terminal-based approach

## [0.5.3] - 2025-12-15

### Added
- TARGET_MODE parameterization for MCP-Shifter (`kali` or `victim`)
  - Same binary serves both target types via environment variable
  - Dynamic column selection based on target mode
  - Tool prefixes match target type (`kali_*` or `victim_*`)
- Victim MCP database user (`victim_mcp_user`) for operational isolation
- Renamed `mcp_user` to `kali_mcp_user` for consistency
- SSM VPC Endpoints for Range VPC (ssm, ssmmessages, ec2messages)
  - Enables Systems Manager access without internet
  - Traffic stays within AWS network
- Custom OpenWebUI Docker image with Cortex theme baked in
  - ECR repository for custom OpenWebUI image
  - Dockerfile extends base image with custom CSS/assets
  - CI/CD builds and deploys themed image automatically
- Victim MCP wrapper for OpenWebUI (`mcp_wrapper_victim.py`)

### Changed
- Replaced mcp-red with mcp-shifter in CI quality workflow
- Architecture docs updated with MCP dual-container diagram
- AgentChat uses custom OpenWebUI image instead of stock ghcr.io image

## Fixed
- Missing s3 permissions to fetch XDR installer
- Fix range user_data fails to account for different installer types

## [0.5.2] - 2025-12-15

### Changed
- Reskin OpenWeb UI UX to match Cortex XDR look and feel

## [0.5.1] - 2025-12-15

### Added
- AWS Network Firewall for Range VPC egress filtering (#251)
- NAT Gateway for private subnet internet access
- Domain allowlists: Victim restricted to XDR endpoints, Kali has no external access

## [0.5.0] - 2025-12-14

### Added
- MCP-Shifter server for OpenWebUI integration (`mcp/mcp-shifter/`)
  - Cognito JWT authentication with per-user session management
  - RDS IAM authentication for range lookup
  - Secrets Manager integration for SSH key retrieval
  - Session limits (per-user and global) with structured logging
  - Idle connection cleanup timer
  - StreamableHTTPServerTransport for MCP over HTTP
- OpenWebUI MCP wrapper tool (`mcp/openwebui-mcp-wrapper/`)
- `cognito_sub` column on Range model for MCP user lookups
- Custom OIDC backend passing Cognito `sub` claim to Range model
- Security context in MCP server description (authorized pentest boundaries)
- VPC peering between Portal VPC and Range VPC for SSH connectivity
- ALB listener rules for `/chat` and `/mcp` path routing
- IAM policies for MCP server (RDS connect, Secrets Manager read)
- Security group rules for SSH from AgentChat to Kali instances
- Cognito app client for OpenWebUI OIDC authentication
- AgentChat docker-compose for local development (`agentchat/`)
- SSH keypair generation in create_kali Lambda (stored in Secrets Manager)
- `kali_ssh_key_secret_arn` field on Range model

### Changed
- AgentChat deployment workflow includes mcp-shifter container
- mark_ready Lambda sets chat_url when range becomes ready
- - AgentChat routing changed from subpath (`/chat/`) to subdomain (`chat.{domain}`)
- ACM certificate includes SAN for `chat.{domain}` subdomain
- Cognito OAuth callbacks updated for subdomain URLs
- ALB listener rules use `host_header` matching instead of `path_pattern`
- Docker layer caching added to portal and agentchat CI/CD workflows (faster builds)

## [0.4.5] - 2025-12-15
### Changed
- Reskin Portal and Risk Register to Cortex XDR look and feel

## [0.4.4] - 2025-12-14

### Changed

- Upgraded patch @modelcontextprotocol/sdk

## [0.4.3] - 2025-12-13

### Added
- Risk Register Django app
-
## [0.4.2] - 2025-12-13

### Added
- OpenWebUI + Bedrock Access Gateway (BAG) for AgentChat
- Sonnet 4.5 and DeepSeek R1 models for AgentChat
- AgentChat infrastructure
- Checkov IaC security scanning in CI and pre-commit
- Dockerfile HEALTHCHECK for portal container

### Changed
- SonarCloud coverage extended to all modules
- GitHub Actions workflows: explicit permissions, removed workflow_dispatch inputs where not needed
- Use SonarQube Cloud automatic analysis instead of CI/CD workflows

### Security
- Full review of lint (ruff, bandit, eslint) and IaC (checkov) findings
- Fixed critical issues: workflow permissions, Dockerfile healthcheck
- Created issues (#214-222) for deferred security hardening (WAF, flow logs, KMS, etc.)
- All checkov findings now have explicit skip comments with issue references

## [0.4.1] - 2025-12-12

### Removed
- LibreChat
- LiteLLM

## [0.4.0] - 2025-12-12

### Added
- Dev environment (`terraform/environments/dev/`)
- Branch-based deployments: `dev` branch → dev, `main` branch → prod
- Bootstrap script for new AWS accounts (`scripts/bootstrap-dev.sh`)

### Changed
- All workflows support environment selection via branch or manual dispatch
- Streamline GitHub Actions workflows for consistency
- Utility scripts work with dev and prod environments
- User updated immediately when range deploy fails

## [0.3.6] - 2025-12-11

### Fixed
- Remove default value from s3_bucket_arn variable (module variables should have no defaults)

## [0.3.5] - 2025-12-11

### Changed
- Make no versioning on user data s3 bucket explicit

## [0.3.4] - 2025-12-11

### Added
- AWS Bedrock as LibreChat LLM provider

### Changed
- LibreChat EC2 instance rebuilds on user_data changes

## [0.3.3] - 2025-12-11

### Changed
- RDS deletion protection enabled for prod database
- Final snapshot enabled before RDS deletion

## [0.3.2] - 2025-12-11

### Added
- Kali EC2 provisioning Lambda (create_kali) with official AWS Marketplace AMI
- Kali security group in Range VPC with bidirectional victim traffic
- kali_instance_id and kali_ip fields on Range model
- Kali cleanup in teardown Lambda
- Range VPC security documentation (security groups, traffic matrix, isolation)

### Changed
- Victim security group now allows all inbound from Kali SG (for attacks)
- Kali security group allows all inbound from Victim SG (reverse shells, C2)

## [0.3.1] - 2025-12-11

### Added
- LibreChat infrastructure (EC2, dedicated subnet, Secrets Manager, Docker Compose)
- LibreChat CI/CD workflows (infra and deploy)
- SSM tunnel script for LibreChat admin access

### Fixed
- Portal/LibreChat infra workflows now trigger on direct push to main, not just upstream cascade

## [0.3.0] - 2025-12-11

### Added
- Provisioner fields on Range model (subnet_id, subnet_cidr, subnet_index, victim_instance_id, step_function_execution_arn)
- IAM Database Authentication on RDS for Lambda provisioner
- Django migration to create provisioner_lambda PostgreSQL user with minimal permissions
- Provisioner Lambda functions (create_subnet, create_victim, create_kali, configure_librechat, cleanup)
- Step Functions state machines for provisioning and teardown with error handling and timeouts
- Victim security group in Range VPC
- Provisioner module wiring to Portal VPC with remote state references
- Portal integration with Step Functions (replaces callback-based stub)
- EC2 IAM permissions for Step Functions execution
- Range failure alarms
- Stale range cleanup
- docs/maintenance.md: RDS maintenance window reference

### Fixed
- Lambda DB queries: `agent_config_id` → `agent_id`, `os_type_id` → `os_id` (Django FK naming)
- Lambda handlers: `range_id[:8]` slice on integer (range_id is int, not UUID)
- db-connect.sh: Added autocommit for INSERT/UPDATE queries
- IAM policy: Fix `ec2:CreateSubnet` permission (unsupported `ec2:Vpc` condition key)
- Cleanup Lambda: Allow teardown from `ready` state (mark_failed=false)

### Removed
- Callback endpoint for provisioner (Lambda writes directly to DB)

## [0.2.9] - 2025-12-09

### Fixed
- AWS_REGION mismatch
- ALB health check errors
- Update docs

## [0.2.8] - 2025-12-09

### Fixed
- Range provisioner missing env var for domain
- Remove default site url for range provisioner

## [0.2.7] - 2025-12-09

### Added
- Dashboard Range launch flow with live status polling
- Range API endpoints (status, launch, cancel, destroy, callback)
- Range model status fields (pending, provisioning, ready, paused, resuming, destroying, destroyed, failed)
- Stub provisioner service with HMAC-signed callback tokens
- Client-side DashboardManager for state management
- State transition validation to prevent callback replay attacks

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
