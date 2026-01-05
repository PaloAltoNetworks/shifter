# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.10.3] - 2025-01-04

## Added
- SSM Documents for Shifter Platform deployment and ASG lifecycle hook

## [0.10.2] - 2025-01-04

### Changed
- GitHub runners replaced with auto-scaling ephemeral runners via terraform-aws-github-runner module
  - Scale from zero on workflow trigger
  - EC2 spot instances for cost savings
  - GitHub App authentication for secure runner registration
- Added runner-deploy.sh script for runner infrastructure management
- Added manual-deployment.md documentation for global terraform stacks


## [0.10.1] - 2025-01-02

### Added
- Cyber range DSL foundation (Shared Schema)
- Interactive cli app for Shifter AWS account bootstrap and infrastructure deployment
- Arch as Code foundation: Code and model level service layer boundary violation detection in CI/CD and pre-commit
- Independent processes consume range status updates
- Claude develop skill
- Centralized code coverage reporting

### Changed

- CMS services extraction edge cases and fixes
- Mission Control re-wire to use services
- Engine services extraction and implementation (excl pause/resume)
  - NGFW services deferred to upcoming patch
  - Mission Control re-wire deferred to upcoming patch
- Model migrations to respect service layer separation
- Redis replication for HA (single-node in dev, replication group in prod)
- SNS/SQS for range status updates with alarms
- Fault-tolerant fully alarmed range status consumer processes
- Unit test coverage improvements

### Fixed
- In-depth help check short circuited by Django middleware
- Remove dead code from service layer refactoring
- Frontend tests not included in pre-commit
- Remove stale Celery references
- Linting
- Some tests not called
- Pre-commit and CI/CD test, lint, quality, and sast coverage
- SonarQube coverage exclusions
- Tests for repo utility apps and Architecture as Code tests

## [0.10.0] - 2025-01-01

### Added
- CMS services extraction and implementation
- Unified Credential model

## [0.9.9] - 2025-12-31

### Added
- Management services implementation
  - cognito_sub update service
  - activity log service
  - user profile service

### Changed
- OIDC backend updated to use management services
- User profile model moved to management domain
- Activity log model moved to management domain

## [0.9.8] - 2025-12-31

### Added
- Portal NGFW Management UI (#416)
  - NGFW list view at `/mission-control/assets/ngfw/`
  - NGFW detail view with AWS resources, PAN-OS info, linked ranges
  - 5-step setup wizard (Name & Credentials → Registration → Confirm → Provisioning → Complete)
  - Deprovision confirmation view with linked ranges warning
  - API endpoints:
    - `GET /api/ngfw/list/` - List user's NGFWs
    - `POST /api/ngfw/` - Start provisioning
    - `GET /api/ngfw/<id>/status/` - Poll provisioning status
    - `POST /api/ngfw/<id>/start/` - Start NGFW
    - `POST /api/ngfw/<id>/stop/` - Stop NGFW
    - `POST /api/ngfw/<id>/deprovision/` - Deprovision NGFW
  - WebSocket consumer for real-time provisioning status updates
  - XDR manual configuration instructions with serial number display
  - 62 tests covering all views and APIs
- Test review skill (`.claude/skills/test-review/`)
  - 6 quality criteria with specific fail indicators
  - Anti-pattern catalog by severity (HIGH/MEDIUM/LOW)
  - Coverage gap detection checklist
  - Scoring formula and fix guidance

### Note
- NGFW API endpoints are stubbed pending Issue #414 (UserNGFWStack)
- UI is complete and functional with simulated provisioning flow

## [0.9.7] - 2025-12-30

### Security
- Hardened GitHub Actions OIDC IAM permissions to limit blast radius (#430)
  - Restricted `iam:CreateRole`, `iam:AttachRolePolicy`, `iam:PutRolePolicy` to specific role name patterns
  - Restricted `iam:CreateInstanceProfile` to matching instance profile patterns
  - Restricted `iam:PassRole` to same role patterns
  - Allowed patterns: `dev-portal-*`, `prod-portal-*`, `dev-range-*`, `prod-range-*`, `shifter-*`, `github-actions-shifter-*`
  - Prevents attacker from creating arbitrary roles with `AdministratorAccess` if GHA is compromised

## [0.9.6] - 2025-12-30

### Added
- S3 cost budget alerts for dev and prod environments
  - Defense-in-depth monitoring for unusual S3 costs
  - Alerts at 80% of $50/month threshold

## [0.9.3] - 2025-12-30

### Added
- Windows victim AMI Packer build (#410)
  - `windows.pkr.hcl` Packer template with WinRM communicator
  - PowerShell provisioning scripts: base, services, tools, claude-code, sysprep
  - XAMPP, IIS, FTP Server, OpenSSH Server
  - Python 3.12, Node.js 20.x, Git
  - Claude Code configured for Bedrock (system PATH at `C:\Program Files\nodejs`)
  - WinRM enabled for remote management
  - Windows Defender disabled via GPO for XDR compatibility
  - EC2Launch v2 sysprep for AMI finalization
- GitHub Actions workflow support for Windows AMI builds

### Changed
- Updated packer README with Windows AMI documentation
- Updated victim-ami.md with Packer build instructions

## [0.9.2] - 2025-12-30

### Added
- Ubuntu victim AMI Packer configuration (#409)
  - `ubuntu.pkr.hcl` template following Kali pattern
  - Provisioning scripts: base.sh, services.sh, tools.sh, claude-code.sh
  - Services: Apache 2.4 with mod_php, MySQL 8.0, Docker, OpenSSH, vsftpd, Samba
  - Development tools: build-essential, Python 3, Node.js 20.x, Git
  - Claude Code configured for AWS Bedrock
- GitHub Actions workflow support for Ubuntu AMI builds
- Ubuntu test classes in shifter/packer/tests/test_packer.py

### Changed
- SSM parameter for victim AMI renamed from `/shifter/ami/victim` to `/shifter/ami/ubuntu`
- Terraform data sources updated for new SSM parameter name

## [0.9.1] - 2025-12-30

### Changed
- Engine architecture refactor (#413)
  - Executors moved to `executors/` (ssm_executor, ssh_executor)
  - Orchestrators moved to `orchestrators/` (setup_orchestrator)
  - Plans moved to `plans/` (setup_plan.py → base.py)
  - RangeStack moved to `stacks/`
  - New: `AWSExecutor`, `OpsOrchestrator` stubs
  - New: Base protocols for executors and orchestrators

## [0.9.0] - 2025-12-30

### Added
- NGFW database models for persistent per-user NGFW support (#412)
  - `SCMCredential` model for Strata Cloud Manager PIN-based registration
  - `NGFWDeploymentProfile` model for Software NGFW Credits authcodes
  - `UserNGFW` model for persistent NGFW instances
  - `Asset` and `Credential` abstract base classes with soft delete and expiration
- Field-level encryption for sensitive credentials using `django-encrypted-model-fields`
  - `scm_pin_value` and `authcode` fields encrypted at rest
  - `FIELD_ENCRYPTION_KEY` environment variable required in production
- Range model fields for NGFW integration
  - `ngfw` FK to UserNGFW (SET_NULL on delete)
  - `gwlb_endpoint_id` for GWLB endpoint tracking
- Django admin for new models (SCMCredential, NGFWDeploymentProfile, UserNGFW)
- Database grants for provisioner_lambda user on new tables
- NGFW infrastructure foundation for persistent per-user NGFW instances (#408)
  - Dedicated /22 subnet (10.1.4.0/22) for ~500 NGFW capacity
  - Management security group (SSH/HTTPS from Portal for management)
  - Dataplane security group (all VPC traffic via GWLB)
  - IAM role with S3 bootstrap read and CloudWatch Logs access
  - CloudWatch alarm for NGFW capacity (>400 triggers SNS alert)
  - Terraform outputs for Engine/Pulumi consumption

### Removed
- `StrataConfig` model (superseded by `SCMCredential` and `NGFWDeploymentProfile`)
- Range fields: `ngfw_enabled`, `strata_config`, `ngfw_instance_id`, `ngfw_untrust_ip`, `ngfw_trust_ip`

## [0.8.9] - 2025-12-29

### Added
- Packer infrastructure for reproducible AMI builds (#273)
- sshpass in Kali AMI for non-interactive SSH (#273)
- GitHub Actions workflow for AMI builds

## [0.8.8] - 2025-12-29

### Changed
- Remove redundant SSH security group rules (#290)

## [0.8.7] - 2025-12-29

### Added
- `standup_duration` property on Range model for tracking provisioning time

## [0.8.6] - 2025-12-29

### Changed
- Remove Step Functions permissions from GitHub OIDC role (cleanup after v1 provisioner removal)

## [0.8.5] - 2025-12-29

### Fixed
- Dashboard dropdown behavior and portal test stability

## [0.8.4] - 2025-12-29

### Changed
- Extract service layer from views.py (engine, cms apps)
- Centralize Range status groupings as frozenset constants

## [0.8.3] - 2025-12-29

### Changes
- Refactor consumers.py for maintanability

## [0.8.2] - 2025-12-27

### Added
- NGFW (VM-Series) support
- Strata Cloud Manager support
- Cortex XDR sidebar submenu styling
- Asset Menu

### Changes
- GitGuardian and Snyk ignore tests

## [0.8.1] - 2025-12-27

### Changed
- Migrate all instances to Shifter Engine
- Docs updated to reflect new architecture and naming conventions

## [0.8.0] - 2025-12-27

### Added
- Domain controller AMI
- Basic AD scenario option with AD join by Windows
- Re-factor Shifter Engine scenario generation for extensibility

### Changed
- SonarQube ignores test files

## [0.7.20] - 2025-12-24

### Added
- JavaScript unit tests for DirectUploader (upload.js) with Jest (#136)
  - 79 tests covering happy paths, failure modes, edge cases, order of operations
  - Proper mocks for fetch, XMLHttpRequest, navigator.sendBeacon, window events
  - `make test-js` and `make test-js-coverage` Makefile targets
  - CI integration via `portal-js-tests` job in quality workflow

## [0.7.19] - 2025-12-24
- Add TDD planning Claude Code skill

## [0.7.18] - 2025-12-24

### Added
- Claude Code Skills for common repo/ops tasks

## [0.7.17] - 2025-12-24

### Changed
- Risk register app is accessible only by admin
- Removed History sidebar item (not yet working)
- Terminal page and link handles no active range gracefully

## [0.7.16] - 2025-12-23

### Added
- Developer documentation section (`docs/dev/`) with onboarding guides
  - Local setup, CI/CD, secrets management, Terraform patterns, engineering principles
- Commit tfvars to repository (no longer gitignored)
- Dev-box admin password auto-generated and stored in Secrets Manager

### Changed
- Removed `*.tfvars` from `.gitignore` - config values are not secrets
- Dev-box no longer requires manual password in tfvars

### Removed
- `terraform.tfvars.example` files (redundant now that tfvars are committed)
- `admin_password` variable from dev-box Terraform

## [0.7.15] - 2025-12-23

### Added
- Documentation section in Mission Control sidebar
- Renders markdown docs from `shifter/shifter_platform/documentation/docs/` with navigation tree
- Mermaid.js diagram support for architecture diagrams
- Cortex XDR dark theme styling for documentation pages

## [0.7.14] - 2025-12-22

### Fixed
- Terminal UI text overflows container

## [0.7.13] - 2025-12-22

### Fixed
- Terminal UI does not show IP address for Windows victims

## [0.7.12] - 2025-12-22

### Added
- Windows victim support in provisioner v2
- Windows victim AMI v3 with XAMPP, Claude Code, Python, Git, IIS, FTP, OpenSSH
- Terminal UI SSH support for Windows victims (Administrator username)
- Database migration granting provisioner SELECT on operatingsystem table

### Fixed
- Range destroy race condition leads to subnet collision
- Django logs not forwarded to CloudWatch
- Windows AMI sysprep: Claude Code installed to system path (`C:\Program Files\nodejs`)
- Windows Defender disabled via policy to avoid XDR conflicts

## [0.7.11] - 2025-12-21

.deb and .rpm packages confirmed fix as part of provisioner v2 in 0.7.7

### Added
- Provisioner confirms assigned subnet index is available before provisioning

### Fixed
- Kali boots slow due to redundant kali headless install
- Failed range auto-cleanup not running in dev


## [0.7.10] - 2025-12-21

### Fixed
- Provisioner fails to install .deb or .rpm agent packages properly
- Provisioner fails to rollback range if agent installation fails

## [0.7.9] - 2025-12-21

### Fixed
- Provisioner uses vars for instance types instead of hardcoded values

## [0.7.8] - 2025-12-21

### Added
- Standing dev box instance for development and testing

## [0.7.7] - 2025-12-21

### Added
- Pulumi-based provisioner for declarative multi-OS range infrastructure
  - ECS Fargate execution with Step Functions orchestration
  - S3/DynamoDB state backend, ECR container registry
  - Reusable components: NetworkComponent, InstanceComponent, RangeStack
  - Instance catalog supporting Kali, Ubuntu, Windows, Amazon Linux
- CI/CD workflow for Pulumi provisioner (`_pulumi-provisioner.yml`)
- Django model fields and service routing for v1 (Lambda) / v2 (Pulumi) provisioners
- Self-hosted GitHub Actions runner for CI/CD

### Changed
- Range instance types bumped to t3.medium (4GB min for Claude Code)
- CI Docker builds use local caching instead of GitHub Actions cache

### Fixed
- Secrets Manager resources now Pulumi-managed (proper lifecycle, no orphans)
- KMS policy, DNS egress, availability zone configuration for ECS tasks
- WebSocket terminal consumer reads from `provisioned_instances` field (v2 provisioner compatibility)

### Removed
- V1 (Lambda) provisioner

## [0.7.6] - 2025-12-19

### Added
- ALB access logs, VPC flow logs, RDS log exports, WAF logging
- XDR CloudTrail integration via CloudFormation (dev and prod)
- CloudWatch alarms for log aggregation (Firehose delivery lag, SQS DLQ)

### Changed
- Replaced Checkov skip comments with actual implementations (CKV_AWS_91, CKV2_AWS_11, CKV_AWS_129)
- Removed unused XDR IAM from Terraform (managed by CloudFormation instead)

### Fixed
- Multiple code quality, security, and code smells

## [0.7.5] - 2025-12-18

### Added
- AWS WAF protection for ALB with rate limiting and AWS managed rules

## [0.7.4] - 2025-12-18

### Added
- ElastiCache Redis module for Django Channels
- Portal autoscaling: launch template, ASG, scaling policies, CloudWatch alarms
- ALB session stickiness for WebSocket affinity
- Lambda auto-fix for range security group SSH rules from Portal VPC

### Changed
- Django Channels uses Redis when `REDIS_HOST` env var set, falls back to InMemory
- EC2 module supports single instance or ASG mode via `enable_autoscaling` flag
- Dev environment: autoscaling enabled with 2 instances
- GitHub Actions portal workflow supports ASG deployment via SSM targeting by tag
- IAM: Added `elasticache_asg` policy for ElastiCache, Auto Scaling, and Launch Template permissions


## [0.7.3] - 2025-12-17

### Fixed
- VPC peering TF drift dev/prod

### Fixed
- Network Firewall blocking XDR agent egress to Cortex cloud
  - Changed from STRICT_ORDER to DEFAULT_ACTION_ORDER for domain allowlist
  - Added Suricata rule to block direct IP connections (SNI bypass prevention)
- XDR agent not registering with tenant after installation
  - Added cortex.conf deployment before running installer script

## [0.7.2] - 2025-12-17

### Changed
- Removed redundant connection status from terminal header
- Increased terminal padding for better readability

## [0.7.1] - 2025-12-16

### Fixed
- XDR agent not installing on victim EC2 instances (#274)
  - Root cause: User data script used `aws s3 cp` but victim EC2 lacks AWS CLI
  - Changed to presigned URL + curl for agent download (no AWS CLI required)
  - Added SSM-based agent verification before marking range as ready
- CI/CD pipeline not updating Step Functions and Lambdas on code changes
  - Root cause: Missing `output_file_mode` in `archive_file` caused inconsistent zip hashes across CI runners
  - Added `output_file_mode = "0666"` to all Lambda archive_file blocks
  - Extracted Step Functions definitions to external ASL JSON files with `templatefile()`
- Dashboard polling errors when session expires during range provisioning
  - CORS errors occurred when API redirected to Cognito for re-authentication
  - Added session expiration detection and automatic redirect to login page
  - Network Firewall blocking XDR agent egress to Cortex cloud
    - Changed from STRICT_ORDER to DEFAULT_ACTION_ORDER for domain allowlist
    - Added Suricata rule to block direct IP connections (SNI bypass prevention)
  - XDR agent not registering with tenant after installation
    - Added cortex.conf deployment before running installer script

### Added
- Agent verification step in provisioning workflow
  - New `verify_agent` Lambda checks installation via SSM RunCommand
  - Step Functions retry loop with 30s intervals (5 min max)
  - Ranges fail fast with descriptive error if agent install fails
- External ASL state machine definitions for better maintainability
  - `provision_range.asl.json`, `teardown_range.asl.json`, `cleanup_stale_ranges.asl.json`

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
