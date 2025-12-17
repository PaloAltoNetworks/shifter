# Feature Specification: Remove OpenWebUI Infrastructure

**Feature Branch**: `261-remove-owui`
**Created**: 2025-12-15
**Status**: Draft
**Input**: User description: "build specs for the constitution. don't worry about the new interface yet, we're just cleaning up"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Clean CI/CD Pipeline (Priority: P1)

As a developer, I want the CI/CD pipeline to pass without OpenWebUI-related build/test steps so that deployments are not blocked by removed components.

**Why this priority**: CI/CD must work for any other development to proceed. A failing pipeline blocks all other work.

**Independent Test**: Run `gh workflow run quality.yml` and verify the workflow completes successfully without MCP-related build failures.

**Acceptance Scenarios**:

1. **Given** the quality.yml workflow runs, **When** mcp-shifter and openwebui-mcp-wrapper directories no longer exist, **Then** the workflow completes without errors.
2. **Given** the deploy.yml workflow runs, **When** agentchat job references are removed, **Then** the deployment completes without errors.

---

### User Story 2 - Clean Terraform State (Priority: P1)

As an infrastructure operator, I want the Terraform codebase free of agentchat references so that `terraform plan` shows no orphaned resources or errors.

**Why this priority**: Terraform errors block all infrastructure changes. This is foundational.

**Independent Test**: Run `terraform plan` in dev/prod environments and verify no errors related to agentchat, mcp_shifter_ecr, or openwebui_ecr resources.

**Acceptance Scenarios**:

1. **Given** agentchat infrastructure has been destroyed via `terraform destroy`, **When** I delete the Terraform code and run `terraform plan`, **Then** no orphaned resources or errors appear.
2. **Given** ECR repository resources are removed from foundation modules, **When** I run `terraform plan`, **Then** the plan shows no changes related to ECR for MCP/OpenWebUI.

---

### User Story 3 - Clean Django Migrations (Priority: P2)

As a developer, I want Django migrations to be consistent and apply cleanly so that database schema management works correctly.

**Why this priority**: Migrations must apply cleanly, but this is less urgent than CI/CD and Terraform.

**Independent Test**: Run `python manage.py migrate` in a fresh database and verify all migrations apply without errors.

**Acceptance Scenarios**:

1. **Given** migrations 0013 and 0014 are removed, **When** I run `python manage.py migrate`, **Then** migrations apply cleanly up to 0015.
2. **Given** the migration chain is intact (0011 → 0012 → 0015), **When** Django checks migrations, **Then** no inconsistencies are detected.

---

### User Story 4 - Clean Documentation (Priority: P3)

As a developer, I want documentation to accurately reflect the current architecture without OpenWebUI/MCP references so that onboarding is not confusing.

**Why this priority**: Documentation cleanup is important but non-blocking.

**Independent Test**: Search all docs for "agentchat", "openwebui", "mcp-shifter" and verify no stale references exist.

**Acceptance Scenarios**:

1. **Given** agentchat documentation directories are deleted, **When** I build the docs, **Then** the build succeeds without broken links.
2. **Given** CLAUDE.md is updated, **When** a developer reads the project overview, **Then** no mention of OpenWebUI or AgentChat appears.

---

### Edge Cases

- What happens if agentchat Terraform hasn't been destroyed first? The code removal should be done AFTER `terraform destroy` to avoid orphaned resources.
- What if migrations 0013/0014 have already been applied to dev? A cleanup migration (0016) may be needed to drop the created users/schemas.
- How do we handle the migration dependency chain? Migration 0015 depends on 0014, so we need to update 0015's dependency to 0012 instead.

## Requirements *(mandatory)*

### Functional Requirements

**Terraform Cleanup:**
- **FR-001**: All agentchat Terraform modules and environments MUST be deleted
- **FR-002**: ECR repository resources for mcp_shifter and openwebui MUST be removed from foundation modules
- **FR-003**: OpenWebUI DB secret MUST be removed from portal Terraform
- **FR-004**: Cognito agentchat client MUST be removed from portal/cognito module

**Code Cleanup:**
- **FR-005**: The `mcp/mcp-shifter/` directory MUST be deleted
- **FR-006**: The `mcp/openwebui-mcp-wrapper/` directory MUST be deleted
- **FR-007**: The `agentchat/` directory MUST be deleted

**CI/CD Cleanup:**
- **FR-008**: The `_agentchat.yml` workflow MUST be deleted
- **FR-009**: Agentchat job references MUST be removed from `deploy.yml`
- **FR-010**: MCP build/test steps MUST be removed from `quality.yml`
- **FR-011**: MCP paths MUST be removed from workflow triggers

**Migration Cleanup:**
- **FR-012**: Migration 0013 (`create_victim_mcp_user.py`) MUST be deleted
- **FR-013**: Migration 0014 (`rename_mcp_user_to_kali_mcp_user.py`) MUST be deleted
- **FR-014**: Migration 0015 MUST be updated to depend on 0012 instead of 0014
- **FR-015**: Migrations 0011, 0012, and 0015 MUST be preserved (still needed)

**Config Cleanup:**
- **FR-016**: `sonar-project.properties` MUST have MCP paths removed
- **FR-017**: `.pre-commit-config.yaml` MUST have MCP paths removed

**Documentation Cleanup:**
- **FR-018**: `docs/src/agentchat/` directory MUST be deleted
- **FR-019**: `docs/src/qa/agentchat-smoke.md` MUST be deleted
- **FR-020**: `specs/226-wire-up-mcp-integration-with-openwebui/` MUST be deleted
- **FR-021**: `docs/src/architecture.md` MUST have agentchat references removed
- **FR-022**: `CLAUDE.md` MUST have agentchat references removed
- **FR-023**: `CHANGELOG.md` MUST have an entry documenting the removal

### Key Entities

- **agentchat**: Terraform module for OpenWebUI chat infrastructure (EC2, VPC peering, ALB rules) - TO BE REMOVED
- **mcp-shifter**: MCP server for Shifter-specific tools - TO BE REMOVED
- **openwebui-mcp-wrapper**: Python wrapper for MCP integration with OpenWebUI - TO BE REMOVED
- **mcp_user/kali_mcp_user**: Database users created for MCP access - TO BE REMOVED via migration cleanup

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `quality.yml` workflow passes with zero MCP-related steps
- **SC-002**: `deploy.yml` workflow passes with zero agentchat job references
- **SC-003**: `terraform plan` in dev and prod shows no agentchat/ECR changes or errors
- **SC-004**: `python manage.py migrate` completes successfully with clean migration chain
- **SC-005**: `grep -r "agentchat\|openwebui\|mcp-shifter" docs/` returns zero results (excluding changelog)
- **SC-006**: Total lines of code removed exceeds 5,000 (reducing technical debt)
- **SC-007**: Repository contains zero references to OpenWebUI infrastructure in active code

## Execution Order

1. **Manual**: Run `terraform destroy` on agentchat environments (dev, then prod)
2. Delete Terraform directories and update foundation modules
3. Delete MCP code directories
4. Delete agentchat directory
5. Update GitHub workflows
6. Update Django migration dependency chain
7. Update config files
8. Delete/update documentation
9. Test quality workflow passes locally
10. Update CHANGELOG.md
