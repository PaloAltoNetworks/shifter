# Guacamole Infrastructure Deployment Checklist

Getting Guacamole infrastructure deployed and running in Portal VPC via CI/CD.

**Scope**: Infrastructure only. No Portal integration, no Range wiring.

**Architecture**: Shared ALB - Guacamole uses Portal ALB via `/guacamole/*` path. Cognito authentication inherited from Portal.

---

## 1. Module Fixes

Fixes to `platform/terraform/modules/guacamole/` before deployment.

### 1.1 Remove All Variable Defaults

Move defaults - values go in prod and dev tfvars files.

- [x] `log_retention_days` - remove `default = 30`
- [x] `guacd_image_tag` - remove `default = "latest"`
- [x] `guacamole_client_image_tag` - remove `default = "latest"`
- [x] `guacd_cpu` - remove `default = 512`
- [x] `guacd_memory` - remove `default = 1024`
- [x] `guacamole_client_cpu` - remove `default = 512`
- [x] `guacamole_client_memory` - remove `default = 1024`
- [x] `guacd_desired_count` - remove `default = 2`
- [x] `guacamole_client_desired_count` - remove `default = 2`
- [x] `db_instance_class` - remove `default = "db.t3.micro"`
- [x] `db_allocated_storage` - remove `default = 20`
- [x] `db_max_allocated_storage` - remove `default = 50`
- [x] `db_engine_version` - remove `default = "16"`
- [x] `db_multi_az` - remove `default = false`
- [x] `db_backup_retention_days` - remove `default = 7`
- [x] `db_deletion_protection` - remove `default = false`
- [x] `db_skip_final_snapshot` - remove `default = true`
- [x] `enable_autoscaling` - remove `default = true`
- [x] `autoscaling_min_capacity` - remove `default = 2`
- [x] `autoscaling_max_capacity` - remove `default = 10`
- [x] `autoscaling_cpu_target` - remove `default = 70`
- [x] `tags` - remove `default = {}`

### 1.2 Delete Variables (No Longer Needed with Shared ALB)

These variables were for a dedicated ALB - remove them entirely:

- [x] Delete `vpc_cidr` (never referenced)
- [x] Delete `domain_name` (no dedicated ALB)
- [x] Delete `health_check_path` (target group uses fixed `/guacamole/`)
- [x] Delete `enable_waf` (Portal ALB already has WAF)
- [x] Delete `enable_access_logs` (Portal ALB already has access logs)
- [x] Delete `logs_bucket_name` (Portal ALB already has access logs)
- [x] Delete `public_subnet_ids` (no ALB in public subnets)

### 1.3 Add Variables for Shared ALB

New inputs to receive Portal ALB resources:

- [x] Add `alb_listener_arn` - Portal ALB HTTPS listener ARN for creating listener rule
- [x] Add `alb_security_group_id` - Portal ALB security group ID for ECS ingress rules
- [x] Add `range_vpc_cidr` - for restricting guacd egress
- [x] Add `guacd_ecr_repository_arn` - for IAM scoping
- [x] Add `guacamole_client_ecr_repository_arn` - for IAM scoping
- [x] Add `secrets_recovery_window_days` - wire to Secrets Manager

```hcl
variable "alb_listener_arn" {
  description = "ARN of the Portal ALB HTTPS listener"
  type        = string
}

variable "alb_security_group_id" {
  description = "Security group ID of the Portal ALB"
  type        = string
}

variable "range_vpc_cidr" {
  description = "CIDR block of the Range VPC (for guacd egress rules)"
  type        = string
}

variable "guacd_ecr_repository_arn" {
  description = "ARN of the guacd ECR repository"
  type        = string
}

variable "guacamole_client_ecr_repository_arn" {
  description = "ARN of the guacamole-client ECR repository"
  type        = string
}

variable "secrets_recovery_window_days" {
  description = "Recovery window in days for Secrets Manager (0 for immediate deletion)"
  type        = number
}
```

### 1.4 Refactor alb.tf for Shared ALB

Replace entire `alb.tf` - no dedicated ALB, just target group + listener rule:

- [x] Delete `aws_lb.guacamole` resource (the ALB itself)
- [x] Delete `aws_acm_certificate.guacamole` resource
- [x] Delete `aws_acm_certificate_validation.guacamole` resource
- [x] Delete `aws_lb_listener.https` resource (443 listener)
- [x] Delete `aws_lb_listener.http` resource (80 redirect listener)
- [x] Delete `aws_wafv2_web_acl.guacamole` resource
- [x] Delete `aws_wafv2_web_acl_association.guacamole` resource
- [x] Keep `aws_lb_target_group.guacamole` - update health check path to `/guacamole/`, matcher to `200,302`
- [x] Add `aws_lb_listener_rule.guacamole` for `/guacamole/*` path on Portal ALB

New `alb.tf` content:

```hcl
# Target Group for guacamole-client
resource "aws_lb_target_group" "guacamole" {
  name        = "${var.name_prefix}-guacamole"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    path                = "/guacamole/"
    matcher             = "200,302"
  }

  stickiness {
    type            = "lb_cookie"
    cookie_duration = 86400  # 24 hours
    enabled         = true
  }

  tags = var.tags
}

# Listener Rule on Portal ALB for /guacamole/* path
resource "aws_lb_listener_rule" "guacamole" {
  listener_arn = var.alb_listener_arn
  priority     = 100  # Before default action

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.guacamole.arn
  }

  condition {
    path_pattern {
      values = ["/guacamole/*", "/guacamole"]
    }
  }

  tags = var.tags
}
```

### 1.5 Security Group Fixes (security.tf)

Delete ALB security group resources:
- [x] Delete `aws_security_group.alb`
- [x] Delete `aws_security_group_rule.alb_http_ingress`
- [x] Delete `aws_security_group_rule.alb_https_ingress`
- [x] Delete `aws_security_group_rule.alb_egress`

Update guacamole-client security group:
- [x] Change `aws_security_group_rule.guacamole_client_from_alb` to use `var.alb_security_group_id` instead of `aws_security_group.alb.id`

Restrict guacd egress to Range VPC only:
- [x] Change `aws_security_group_rule.guacd_rdp_egress` cidr_blocks from `["0.0.0.0/0"]` to `[var.range_vpc_cidr]`
- [x] Change `aws_security_group_rule.guacd_vnc_egress` cidr_blocks from `["0.0.0.0/0"]` to `[var.range_vpc_cidr]`
- [x] Change `aws_security_group_rule.guacd_ssh_egress` cidr_blocks from `["0.0.0.0/0"]` to `[var.range_vpc_cidr]`

### 1.6 Resource Fixes

- [x] `rds.tf`: Wire `recovery_window_in_days` to variable (currently hardcoded 0)
- [x] `main.tf`: Change service discovery `failure_threshold` from 1 to 3
- [x] `iam.tf`: Scope ECR permissions to specific repository ARNs
- [x] `ecs.tf`: Update `depends_on` in `aws_ecs_service.guacamole_client` - remove `aws_lb_listener.https` (will be deleted), add `aws_lb_listener_rule.guacamole`

### 1.7 Health Check Fix

- [x] `ecs.tf`: guacd health check uses `nc` which isn't in official image
  - **Chose Option A**: Removed health check, rely on ECS task health
  - GitHub issue #518 created to investigate alternatives

### 1.8 Database Auto-Init Environment Variable

- [x] `ecs.tf`: Add to guacamole-client container `environment` block:
  ```hcl
  { name = "POSTGRESQL_AUTO_CREATE_ACCOUNTS", value = "true" }
  ```
  This enables automatic schema creation on first startup.

### 1.9 Update outputs.tf

Remove ALB/ACM outputs (resources being deleted):

- [x] Delete `alb_arn` output
- [x] Delete `alb_dns_name` output
- [x] Delete `alb_zone_id` output
- [x] Delete `certificate_arn` output
- [x] Delete `certificate_domain_validation_options` output
- [x] Delete `alb_security_group_id` output
- [x] Keep `target_group_arn` output (already exists)

---

## 2. VPC/Networking

Guacamole runs in Portal VPC, uses existing peering to reach Range VPC.

### 2.1 Current Architecture

Portal VPC already has:
- [x] VPC peering to Range VPC (`aws_vpc_peering_connection.portal_to_range`)
- [x] Routes from Portal private subnets to Range VPC CIDR
- [x] Routes from Range private subnets to Portal VPC CIDR

Guacamole ECS tasks will run in Portal private subnets and can reach Range instances via this peering.

### 2.2 No Additional VPC Changes Required

The existing peering handles connectivity. The only change needed is in the Guacamole module itself:
- [x] Pass `range_vpc_cidr` to module (see Section 1.3) ✓ Done in 1.3
- [x] Update security group egress rules to use this CIDR (see Section 1.5) ✓ Done in 1.5

### 2.3 Traffic Flow (Shared ALB)

```
User Browser
    ↓ HTTPS (443)
Portal ALB (Portal public subnets)
    ↓ Path: /guacamole/* → Listener Rule
    ↓ HTTP (8080)
guacamole-client ECS (Portal private subnets)
    ↓ Guacamole protocol (4822)
guacd ECS (Portal private subnets)
    ↓ RDP/VNC/SSH (3389/5900/22) via VPC peering
Range instances (Range VPC private subnets)
```

**Note**: With OIDC enabled (Section 9), Guacamole authenticates users directly via Cognito. Users are redirected to Cognito login when accessing `/guacamole/`.

---

## 3. Container Images

ECR repos exist in foundation. Need images pushed.

### 3.1 Verify ECR Repos Exist

**Dev** - Foundation terraform (`environments/dev/main.tf`):
- [x] Verify `shifter-dev-guacd` ECR repo defined
  - Defined at `environments/dev/main.tf:50` (module `guacd_ecr`)
  - **Not yet deployed to AWS** - will be created when foundation terraform is applied
- [x] Verify `shifter-dev-guacamole-client` ECR repo defined
  - Defined at `environments/dev/main.tf:79` (module `guacamole_client_ecr`)
  - **Not yet deployed to AWS** - will be created when foundation terraform is applied

**Prod** - Foundation terraform (`environments/prod/main.tf`):
- [x] Added `shifter-guacd` ECR repo (module `guacd_ecr`)
- [x] Added `shifter-guacamole-client` ECR repo (module `guacamole_client_ecr`)
- [x] Added variables to `environments/prod/variables.tf`
- [x] Added outputs to `environments/prod/outputs.tf`

### 3.2 CI/CD Image Push (Automated)

Images are pushed automatically by the `push-guacamole-images` job in `_shifter-platform.yml`:

- [x] Added `push-guacamole-images` job to `.github/workflows/_shifter-platform.yml`
  - Runs after `plan`, before `apply`
  - Pulls official images from Docker Hub
  - Tags and pushes to ECR with version tag + `latest`
  - Idempotent: skips if image already exists in ECR

**Images pushed:**
- `guacamole/guacd:1.5.5` → `shifter-{env}-guacd:1.5.5` + `:latest`
- `guacamole/guacamole:1.5.5` → `shifter-{env}-guacamole-client:1.5.5` + `:latest`

**To update Guacamole version:**
1. Update `GUACAMOLE_VERSION` in `_shifter-platform.yml`
2. Update `guacd_image_tag` and `guacamole_client_image_tag` in tfvars

### 3.3 Image Tag Strategy

- [x] Using specific version tags (`1.5.5`) instead of `latest` for reproducibility
- [x] Both version tag and `latest` pushed to ECR for flexibility
- [x] tfvars should use the specific version: `guacd_image_tag = "1.5.5"`

---

## 4. Portal Terraform Integration

Add Guacamole module to Portal terraform so CI/CD deploys it.

**Note**: Changes needed in BOTH `dev/portal` AND `prod/portal`.

### 4.1 Add Module to Portal main.tf

Files:
- `platform/terraform/environments/dev/portal/main.tf`
- `platform/terraform/environments/prod/portal/main.tf`

**Dev:**
- [x] Add module block after the `pulumi_provisioner` module
- [x] Added Guacamole log groups to `log_aggregation` module

**Prod:**
- [x] Add module block after the `pulumi_provisioner` module
- [x] Added Guacamole log groups to `log_aggregation` module

```hcl
# ------------------------------------------------------------------------------
# Guacamole (Remote Desktop Gateway)
# ------------------------------------------------------------------------------

module "guacamole" {
  source = "../../../modules/guacamole"

  name_prefix = local.name_prefix
  environment = var.environment
  tags        = var.tags

  # Networking (Portal VPC)
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  range_vpc_cidr     = data.terraform_remote_state.range.outputs.vpc_cidr

  # Shared ALB (from Portal ALB module)
  alb_listener_arn      = module.alb.https_listener_arn
  alb_security_group_id = module.alb.security_group_id

  # ECR (from foundation remote state)
  guacd_ecr_repository_url            = data.terraform_remote_state.foundation.outputs.guacd_ecr_url
  guacd_ecr_repository_arn            = data.terraform_remote_state.foundation.outputs.guacd_ecr_arn
  guacamole_client_ecr_repository_url = data.terraform_remote_state.foundation.outputs.guacamole_client_ecr_url
  guacamole_client_ecr_repository_arn = data.terraform_remote_state.foundation.outputs.guacamole_client_ecr_arn

  # Logging (shared with portal)
  log_retention_days = var.log_retention_days

  # Container configuration
  guacd_image_tag            = var.guacd_image_tag
  guacamole_client_image_tag = var.guacamole_client_image_tag
  guacd_cpu                  = var.guacd_cpu
  guacd_memory               = var.guacd_memory
  guacamole_client_cpu       = var.guacamole_client_cpu
  guacamole_client_memory    = var.guacamole_client_memory
  guacd_desired_count            = var.guacd_desired_count
  guacamole_client_desired_count = var.guacamole_client_desired_count

  # Database configuration
  db_instance_class        = var.guacamole_db_instance_class
  db_allocated_storage     = var.guacamole_db_allocated_storage
  db_max_allocated_storage = var.guacamole_db_max_allocated_storage
  db_engine_version        = var.guacamole_db_engine_version
  db_multi_az              = var.guacamole_db_multi_az
  db_backup_retention_days = var.guacamole_db_backup_retention_days
  db_deletion_protection   = var.guacamole_db_deletion_protection
  db_skip_final_snapshot   = var.guacamole_db_skip_final_snapshot

  # Autoscaling
  enable_autoscaling       = var.guacamole_enable_autoscaling
  autoscaling_min_capacity = var.guacamole_autoscaling_min_capacity
  autoscaling_max_capacity = var.guacamole_autoscaling_max_capacity
  autoscaling_cpu_target   = var.guacamole_autoscaling_cpu_target

  # Secrets
  secrets_recovery_window_days = var.guacamole_secrets_recovery_window_days
}
```

### 4.2 Add Variables to Portal variables.tf

Files:
- `platform/terraform/environments/dev/portal/variables.tf`
- `platform/terraform/environments/prod/portal/variables.tf`

**Dev:**
- [x] Add all Guacamole-specific variables (no defaults)

**Prod:**
- [x] Add all Guacamole-specific variables (no defaults)

```hcl
# ------------------------------------------------------------------------------
# Guacamole
# ------------------------------------------------------------------------------

variable "guacd_image_tag" {
  description = "Docker image tag for guacd"
  type        = string
}

variable "guacamole_client_image_tag" {
  description = "Docker image tag for guacamole-client"
  type        = string
}

variable "guacd_cpu" {
  description = "CPU units for guacd task"
  type        = number
}

variable "guacd_memory" {
  description = "Memory in MB for guacd task"
  type        = number
}

variable "guacamole_client_cpu" {
  description = "CPU units for guacamole-client task"
  type        = number
}

variable "guacamole_client_memory" {
  description = "Memory in MB for guacamole-client task"
  type        = number
}

variable "guacd_desired_count" {
  description = "Desired number of guacd tasks"
  type        = number
}

variable "guacamole_client_desired_count" {
  description = "Desired number of guacamole-client tasks"
  type        = number
}

variable "guacamole_db_instance_class" {
  description = "RDS instance class for Guacamole database"
  type        = string
}

variable "guacamole_db_allocated_storage" {
  description = "Allocated storage for Guacamole RDS in GB"
  type        = number
}

variable "guacamole_db_max_allocated_storage" {
  description = "Maximum storage for Guacamole RDS autoscaling in GB"
  type        = number
}

variable "guacamole_db_engine_version" {
  description = "PostgreSQL engine version for Guacamole"
  type        = string
}

variable "guacamole_db_multi_az" {
  description = "Enable Multi-AZ for Guacamole RDS"
  type        = bool
}

variable "guacamole_db_backup_retention_days" {
  description = "Backup retention days for Guacamole RDS"
  type        = number
}

variable "guacamole_db_deletion_protection" {
  description = "Enable deletion protection for Guacamole RDS"
  type        = bool
}

variable "guacamole_db_skip_final_snapshot" {
  description = "Skip final snapshot for Guacamole RDS"
  type        = bool
}

variable "guacamole_enable_autoscaling" {
  description = "Enable autoscaling for Guacamole ECS services"
  type        = bool
}

variable "guacamole_autoscaling_min_capacity" {
  description = "Minimum capacity for Guacamole autoscaling"
  type        = number
}

variable "guacamole_autoscaling_max_capacity" {
  description = "Maximum capacity for Guacamole autoscaling"
  type        = number
}

variable "guacamole_autoscaling_cpu_target" {
  description = "CPU target for Guacamole autoscaling"
  type        = number
}

variable "guacamole_secrets_recovery_window_days" {
  description = "Recovery window for Guacamole secrets (0 for dev, 7+ for prod)"
  type        = number
}
```

### 4.3 Add Values to Portal terraform.tfvars

Files:
- `platform/terraform/environments/dev/portal/terraform.tfvars`
- `platform/terraform/environments/prod/portal/terraform.tfvars`

**Dev:**
- [x] Add all Guacamole values (see below)

**Prod:**
- [x] Add all Guacamole values (with prod-appropriate settings: multi_az=true, deletion_protection=true, etc.)

```hcl
# ------------------------------------------------------------------------------
# Guacamole
# ------------------------------------------------------------------------------

guacd_image_tag                = "1.5.5"
guacamole_client_image_tag     = "1.5.5"
guacd_cpu                      = 512
guacd_memory                   = 1024
guacamole_client_cpu           = 512
guacamole_client_memory        = 1024
guacd_desired_count            = 1
guacamole_client_desired_count = 1

# Database
guacamole_db_instance_class        = "db.t3.small"
guacamole_db_allocated_storage     = 20
guacamole_db_max_allocated_storage = 50
guacamole_db_engine_version        = "16"
guacamole_db_multi_az              = false
guacamole_db_backup_retention_days = 7
guacamole_db_deletion_protection   = false
guacamole_db_skip_final_snapshot   = true

# Autoscaling (disabled for initial testing)
guacamole_enable_autoscaling       = false
guacamole_autoscaling_min_capacity = 1
guacamole_autoscaling_max_capacity = 4
guacamole_autoscaling_cpu_target   = 70

# Secrets
guacamole_secrets_recovery_window_days = 0
```

### 4.4 Add Outputs to Portal outputs.tf

Files:
- `platform/terraform/environments/dev/portal/outputs.tf`
- `platform/terraform/environments/prod/portal/outputs.tf`

**Dev:**
- [x] Add Guacamole outputs

**Prod:**
- [x] Add Guacamole outputs
  ```hcl
  # ------------------------------------------------------------------------------
  # Guacamole
  # ------------------------------------------------------------------------------

  output "guacamole_target_group_arn" {
    description = "ARN of the Guacamole target group"
    value       = module.guacamole.target_group_arn
  }
  ```

---

## 5. CI/CD Path Detection Update

Update deploy.yml to detect Guacamole module changes.

### 5.1 Update Change Detection

File: `.github/workflows/deploy.yml`

- [x] Add guacamole module to `shifter_platform` paths:
  ```yaml
  shifter_platform:
    - 'platform/terraform/modules/portal/**'
    - 'platform/terraform/modules/guacamole/**'  # ADD THIS
    - 'platform/terraform/environments/*/portal/**'
    - 'shifter/**'
    - '.github/workflows/_shifter-platform.yml'
  ```

This ensures changes to the Guacamole module trigger the Platform workflow.

---

## 6. Verification

After CI/CD completes:

### 6.1 Infrastructure Checks

- [ ] ECS cluster exists and is ACTIVE
- [ ] guacd service running (check ECS console)
- [ ] guacamole-client service running
- [ ] RDS instance available
- [ ] Target group healthy (check Portal ALB target groups)
- [ ] Listener rule exists for `/guacamole/*` path
- [ ] Service discovery namespace created

### 6.2 Access Check

- [ ] Browse to `https://dev.shifter.keplerops.com/guacamole/`
- [ ] Should redirect to Cognito login (Guacamole OIDC)
- [ ] After Cognito login, should be logged into Guacamole as email address
- [ ] User should see Guacamole home screen (no secondary login required)

**Note**: With OIDC enabled, users authenticate via Cognito directly. The `guacadmin` user still exists for admin tasks but regular users use Cognito SSO.

### 6.3 Troubleshooting

If ECS tasks fail:
- [ ] Check CloudWatch logs: `/ecs/{name_prefix}-guacd`
- [ ] Check CloudWatch logs: `/ecs/{name_prefix}-guacamole-client`
- [ ] Verify ECR images exist and are pullable
- [ ] Check security groups allow necessary traffic
- [ ] Check RDS connectivity from ECS tasks

If target group unhealthy:
- [ ] Check guacamole-client is listening on port 8080
- [ ] Check health check path returns 200 or 302
- [ ] Check Portal ALB security group allows outbound to ECS

---

## 7. Database Schema Initialization

The Guacamole PostgreSQL database needs schema initialization before first use.

### 7.1 Official Image Behavior

The `guacamole/guacamole` Docker image supports automatic schema creation via environment variables:

- `POSTGRESQL_AUTO_CREATE_ACCOUNTS=true` - Creates default `guacadmin` user
- The image checks if tables exist on startup and runs init SQL if missing

**Fix required:** See Section 1.8 - add env var to ecs.tf

### 7.2 If Auto-Init Fails

If the official image doesn't auto-initialize (check CloudWatch logs for errors):

1. Download schema files from Apache:
   - `001-create-schema.sql` - Creates tables
   - `002-create-admin-user.sql` - Creates guacadmin user

2. Connect to RDS and run manually:
   ```bash
   # Get credentials from Secrets Manager
   aws secretsmanager get-secret-value \
     --secret-id shifter-dev-portal-guacamole-db \
     --query SecretString --output text | jq -r '.password'

   # Connect via bastion or SSM port forward
   psql -h <rds-endpoint> -U guacamole_admin -d guacamole < 001-create-schema.sql
   psql -h <rds-endpoint> -U guacamole_admin -d guacamole < 002-create-admin-user.sql
   ```

### 7.3 Schema SQL Reference

- https://github.com/apache/guacamole-client/tree/main/extensions/guacamole-auth-jdbc/modules/guacamole-auth-jdbc-postgresql/schema

---

## 8. Secrets Management

The Guacamole module is self-contained for secrets - no portal integration required.

### 8.1 Module-Created Secrets

The module creates its own secret in `rds.tf`:
- Secret name: `shifter-{name_prefix}-guacamole-db`
- Contains: `username`, `password`, `host`, `port`, `dbname`, `engine`

### 8.2 IAM Permissions

Already configured in `iam.tf`:
- [x] ECS execution role can read the secret (for container startup)
- [x] guacamole-client task role can read the secret (for runtime)

### 8.3 Recovery Window Fix

Currently hardcoded to 0 days (immediate deletion). See Section 1.3 and 1.6:
- [x] Add `secrets_recovery_window_days` variable (done in 1.3)
- [x] Wire to `aws_secretsmanager_secret.db_credentials.recovery_window_in_days` (done in 1.6)
- [x] Set to 0 for dev, 7+ for prod in tfvars (done in 4.3)

---

## 9. OIDC/Cognito Authentication

Guacamole authenticates via Cognito OIDC instead of its own login page.

### 9.1 Custom Docker Image

The official `guacamole/guacamole` image doesn't include the OIDC extension. Created custom image:

- [x] Created `shifter/engine/guacamole/Dockerfile` with OIDC extension
- [x] Updated CI/CD to build custom image instead of mirroring

**Dockerfile location:** `shifter/engine/guacamole/Dockerfile`

**Extension:** `guacamole-auth-sso-openid-1.5.5.jar` downloaded from Apache archive

### 9.2 Cognito App Client

Guacamole needs its own Cognito app client with specific callback URLs:

- [x] Added `cognito.tf` to Guacamole module
- [x] Creates `aws_cognito_user_pool_client.guacamole` when OIDC enabled
- [x] Callback URL: `https://{domain}/guacamole/`
- [x] Uses implicit flow (required by Guacamole OIDC extension)

### 9.3 Module Variables

New OIDC-related variables added to Guacamole module:

- [x] `enable_oidc` - Toggle OIDC authentication (bool)
- [x] `cognito_user_pool_id` - Portal's Cognito user pool ID
- [x] `cognito_domain` - Cognito hosted UI domain URL
- [x] `aws_region` - For constructing JWKS endpoint
- [x] `domain_name` - Portal domain for redirect URI

### 9.4 ECS Environment Variables

When OIDC is enabled, these env vars are passed to guacamole-client:

- [x] `OPENID_AUTHORIZATION_ENDPOINT` - Cognito OAuth2 authorize URL
- [x] `OPENID_JWKS_ENDPOINT` - Cognito JWKS URL for token validation
- [x] `OPENID_ISSUER` - Cognito issuer URL
- [x] `OPENID_CLIENT_ID` - Guacamole's Cognito app client ID
- [x] `OPENID_REDIRECT_URI` - `https://{domain}/guacamole/`
- [x] `OPENID_SCOPE` - `openid email profile`
- [x] `OPENID_USERNAME_CLAIM_TYPE` - `email`

### 9.5 Portal Integration

- [x] Added `guacamole_enable_oidc` variable to portal variables.tf (dev + prod)
- [x] Added `guacamole_enable_oidc = true` to terraform.tfvars (dev + prod)
- [x] Pass Cognito values from Portal Cognito module to Guacamole module

### 9.6 Authentication Flow

With OIDC enabled:
1. User visits `https://portal.domain/guacamole/`
2. Guacamole redirects to Cognito login page
3. User authenticates with Cognito (MFA required)
4. Cognito redirects back to Guacamole with auth token
5. Guacamole validates token via JWKS endpoint
6. User is logged in as their email address

**Note**: The default `guacadmin` user still exists for admin tasks, but regular users authenticate via Cognito.
