# OpenWebUI Cleanup Plan

Remove OpenWebUI and MCP infrastructure. Replace with Django Channels terminal (separate task).

## Phase 1: Terraform Destroy (Manual)

Before removing code, destroy the agentchat infrastructure in AWS:

```bash
cd terraform/environments/dev/agentchat
terraform destroy
```

This removes:
- AgentChat EC2 instance
- VPC peering (Portal ↔ Range)
- ALB target groups and listener rules
- Security group rules

## Phase 2: Remove Terraform Code

### Delete agentchat module and environments
```
terraform/modules/agentchat/           # Delete entire directory
terraform/environments/dev/agentchat/  # Delete entire directory
terraform/environments/prod/agentchat/ # Delete entire directory
```

### Remove ECR repositories from foundation
**Files:**
- `terraform/environments/dev/main.tf` - Remove `mcp_shifter_ecr` and `openwebui_ecr` resources
- `terraform/environments/dev/outputs.tf` - Remove ECR outputs
- `terraform/environments/prod/main.tf` - Same
- `terraform/environments/prod/outputs.tf` - Same

### Remove OpenWebUI DB secret from portal
**Files:**
- `terraform/environments/dev/portal/main.tf` - Remove `openwebui_db` secret resource
- `terraform/environments/dev/portal/outputs.tf` - Remove `openwebui_db_secret_arn` output
- `terraform/environments/prod/portal/main.tf` - Same
- `terraform/environments/prod/portal/outputs.tf` - Same

### Remove Cognito agentchat client
**Files:**
- `terraform/modules/portal/cognito/main.tf` - Remove `agentchat_client_id` and `agentchat_secret_arn`
- `terraform/modules/portal/cognito/outputs.tf` - Remove agentchat outputs

## Phase 3: Remove MCP Code

### Delete MCP directories
```
mcp/mcp-shifter/              # Delete entire directory
mcp/openwebui-mcp-wrapper/    # Delete entire directory
```

### Delete agentchat directory
```
agentchat/                    # Delete entire directory (Dockerfile, docker-compose, custom-theme)
```

## Phase 4: Update GitHub Actions

### Delete agentchat workflow
```
.github/workflows/_agentchat.yml  # Delete file
```

### Update deploy.yml
**File:** `.github/workflows/deploy.yml`
- Remove agentchat job
- Remove agentchat from `needs` arrays
- Remove agentchat change detection

### Update quality.yml
**File:** `.github/workflows/quality.yml`
- Remove mcp-shifter build/test steps
- Remove openwebui-mcp-wrapper test step
- Remove mcp paths from cache-dependency-path
- Remove mcp paths from `on.push.paths` and `on.pull_request.paths`

## Phase 5: Database Migrations

### Keep these migrations (still needed)
- `0011_create_mcp_user.py` - Keep, will be used by Django Channels terminal
- `0012_range_victim_ssh_key_secret_arn.py` - Keep, Range model needs this column
- `0015_grant_victim_ssh_key_to_provisioner.py` - Keep, provisioner needs this

### Remove these migrations
- `0013_create_victim_mcp_user.py` - Delete (victim_schema, victim_mcp_user no longer needed)
- `0014_rename_mcp_user_to_kali_mcp_user.py` - Delete (keep mcp_user as-is)

### Create squash migration
New migration to clean up the removed users:
```python
# 0016_remove_mcp_users.py
migrations.RunSQL(
    sql="""
        DROP USER IF EXISTS kali_mcp_user;
        DROP USER IF EXISTS victim_mcp_user;
        DROP SCHEMA IF EXISTS victim_schema CASCADE;
    """,
    reverse_sql="-- No reverse, these users are recreated by 0013/0014 if needed"
)
```

**Note:** If 0013/0014 haven't been applied to dev yet, we can just delete them. If they have, we need the cleanup migration.

## Phase 6: Update Config Files

### sonar-project.properties
- Remove `mcp/openwebui-mcp-wrapper` from test sources

### .pre-commit-config.yaml
- Remove `mcp/openwebui-mcp-wrapper` from paths

### CHANGELOG.md
- Add entry for OWUI removal (don't delete history)

## Phase 7: Remove Documentation

### Delete agentchat docs
```
docs/src/agentchat/           # Delete entire directory
docs/src/qa/agentchat-smoke.md  # Delete file
specs/226-wire-up-mcp-integration-with-openwebui/  # Delete entire directory
```

### Update architecture docs
- `docs/src/architecture.md` - Remove agentchat references
- `docs/src/range/provisioner.md` - Remove chat_url references (or mark as deprecated)

## Phase 8: Update CLAUDE.md

Remove agentchat references from the project overview and architecture diagrams.

---

## Files Summary

### Delete (directories)
- `terraform/modules/agentchat/`
- `terraform/environments/dev/agentchat/`
- `terraform/environments/prod/agentchat/`
- `mcp/mcp-shifter/`
- `mcp/openwebui-mcp-wrapper/`
- `agentchat/`
- `docs/src/agentchat/`
- `specs/226-wire-up-mcp-integration-with-openwebui/`

### Delete (files)
- `.github/workflows/_agentchat.yml`
- `docs/src/qa/agentchat-smoke.md`
- `portal/mission_control/migrations/0013_create_victim_mcp_user.py`
- `portal/mission_control/migrations/0014_rename_mcp_user_to_kali_mcp_user.py`

### Modify
- `terraform/environments/dev/main.tf` - Remove ECR repos
- `terraform/environments/dev/outputs.tf` - Remove ECR outputs
- `terraform/environments/prod/main.tf` - Remove ECR repos
- `terraform/environments/prod/outputs.tf` - Remove ECR outputs
- `terraform/environments/dev/portal/main.tf` - Remove openwebui_db secret
- `terraform/environments/dev/portal/outputs.tf` - Remove openwebui_db output
- `terraform/environments/prod/portal/main.tf` - Remove openwebui_db secret
- `terraform/environments/prod/portal/outputs.tf` - Remove openwebui_db output
- `terraform/modules/portal/cognito/main.tf` - Remove agentchat client
- `terraform/modules/portal/cognito/outputs.tf` - Remove agentchat outputs
- `.github/workflows/deploy.yml` - Remove agentchat job
- `.github/workflows/quality.yml` - Remove mcp build/test steps
- `sonar-project.properties` - Remove mcp paths
- `.pre-commit-config.yaml` - Remove mcp paths
- `docs/src/architecture.md` - Remove agentchat references
- `CLAUDE.md` - Remove agentchat references
- `CHANGELOG.md` - Add removal entry

### Create
- `portal/mission_control/migrations/0016_remove_mcp_users.py` (if needed)

---

## Execution Order

1. `terraform destroy` on agentchat environments (manual)
2. Delete Terraform directories/files
3. Delete MCP code directories
4. Delete agentchat directory
5. Update GitHub workflows
6. Handle Django migrations
7. Update config files
8. Update/delete documentation
9. Test quality workflow passes
10. Commit and push

---

**Version**: 3.0.0 | **Ratified**: 2025-12-15 | **Last Amended**: 2025-12-15
