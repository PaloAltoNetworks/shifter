# Cleanup Checklist: Remove OpenWebUI Infrastructure

**Purpose**: Track completion of all OWUI removal tasks
**Created**: 2025-12-15
**Feature**: [spec.md](spec.md)

## Pre-Flight (Manual)

- [x] CHK001 Run `terraform destroy` in `terraform/environments/dev/agentchat`
- [x] CHK002 Run `terraform destroy` in `terraform/environments/prod/agentchat`
- [x] CHK003 Verify no agentchat EC2 instances remain in AWS console

## Terraform Cleanup

- [x] CHK004 Delete `terraform/modules/agentchat/` directory
- [x] CHK005 Delete `terraform/environments/dev/agentchat/` directory
- [x] CHK006 Delete `terraform/environments/prod/agentchat/` directory
- [x] CHK007 Remove `mcp_shifter_ecr` from `terraform/environments/dev/main.tf`
- [x] CHK008 Remove `openwebui_ecr` from `terraform/environments/dev/main.tf`
- [x] CHK009 Remove ECR outputs from `terraform/environments/dev/outputs.tf`
- [x] CHK010 Remove `mcp_shifter_ecr` from `terraform/environments/prod/main.tf`
- [x] CHK011 Remove `openwebui_ecr` from `terraform/environments/prod/main.tf`
- [x] CHK012 Remove ECR outputs from `terraform/environments/prod/outputs.tf`
- [x] CHK013 Remove `openwebui_db` secret from `terraform/environments/dev/portal/main.tf`
- [x] CHK014 Remove `openwebui_db_secret_arn` from `terraform/environments/dev/portal/outputs.tf`
- [x] CHK015 Remove `openwebui_db` secret from `terraform/environments/prod/portal/main.tf`
- [x] CHK016 Remove `openwebui_db_secret_arn` from `terraform/environments/prod/portal/outputs.tf`
- [x] CHK017 Remove `agentchat_client_id` from `terraform/modules/portal/cognito/main.tf`
- [x] CHK018 Remove `agentchat_secret_arn` from `terraform/modules/portal/cognito/main.tf`
- [x] CHK019 Remove agentchat outputs from `terraform/modules/portal/cognito/outputs.tf`

## Code Cleanup

- [x] CHK020 Delete `mcp/mcp-shifter/` directory
- [x] CHK021 Delete `mcp/openwebui-mcp-wrapper/` directory
- [x] CHK022 Delete `agentchat/` directory

## CI/CD Cleanup

- [x] CHK023 Delete `.github/workflows/_agentchat.yml`
- [x] CHK024 Remove agentchat job from `.github/workflows/deploy.yml`
- [x] CHK025 Remove agentchat from `needs` arrays in `.github/workflows/deploy.yml`
- [x] CHK026 Remove agentchat change detection from `.github/workflows/deploy.yml`
- [x] CHK027 Remove mcp-shifter build/test step from `.github/workflows/quality.yml`
- [x] CHK028 Remove openwebui-mcp-wrapper test step from `.github/workflows/quality.yml`
- [x] CHK029 Remove mcp paths from cache-dependency-path in `.github/workflows/quality.yml`
- [x] CHK030 Remove `mcp/**` from `on.push.paths` in `.github/workflows/quality.yml`
- [x] CHK031 Remove `mcp/**` from `on.pull_request.paths` in `.github/workflows/quality.yml`

## Django Migrations

- [x] CHK032 Delete `portal/mission_control/migrations/0013_create_victim_mcp_user.py`
- [x] CHK033 Delete `portal/mission_control/migrations/0014_rename_mcp_user_to_kali_mcp_user.py`
- [x] CHK034 Update `0015_grant_victim_ssh_key_to_provisioner.py` dependency from 0014 to 0012
- [ ] CHK035 Verify `python manage.py migrate --check` passes

## Config Files

- [x] CHK036 Remove MCP paths from `sonar-project.properties`
- [x] CHK037 Remove MCP paths from `.pre-commit-config.yaml`

## Documentation

- [x] CHK038 Delete `docs/src/agentchat/` directory
- [x] CHK039 Delete `docs/src/qa/agentchat-smoke.md`
- [x] CHK040 Delete `specs/226-wire-up-mcp-integration-with-openwebui/` directory
- [x] CHK041 Remove agentchat references from `docs/src/architecture.md`
- [x] CHK042 Remove agentchat references from `CLAUDE.md`
- [x] CHK043 Add removal entry to `CHANGELOG.md`

## Verification

- [ ] CHK044 Run quality workflow locally and verify it passes
- [ ] CHK045 Run `terraform plan` in dev and verify no errors
- [x] CHK046 Search for stale references: `grep -r "agentchat\|openwebui\|mcp-shifter" --include="*.tf" --include="*.yml" --include="*.md"`
- [ ] CHK047 Verify no broken imports in Python code
- [ ] CHK048 Verify documentation builds without errors

## Notes

- Check items off as completed: `[x]`
- Terraform destroy MUST be done before deleting Terraform code
- Migration dependency chain must be intact: 0011 → 0012 → 0015
