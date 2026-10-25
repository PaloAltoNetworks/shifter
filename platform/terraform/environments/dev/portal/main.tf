terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  name_prefix                      = "${var.environment}-portal"
  iam_name_prefix                  = "shifter-${var.environment}-portal"
  ci_role_permissions_boundary_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/shifter-${var.environment}-ci-role-boundary"
  # Add padding to field_encryption_key (b64_url doesn't include padding, but Fernet requires it)
  field_encryption_key_padded = "${random_id.field_encryption_key.b64_url}="
}

# ------------------------------------------------------------------------------
# Remote State - Foundation (ECR)
# ------------------------------------------------------------------------------

data "terraform_remote_state" "foundation" {
  backend = "s3"
  config = {
    bucket = var.terraform_state_bucket
    key    = "shifter/dev/terraform.tfstate"
    region = var.terraform_state_region
  }
}

# ------------------------------------------------------------------------------
# Remote State - Range VPC
# ------------------------------------------------------------------------------

data "terraform_remote_state" "range" {
  backend = "s3"
  config = {
    bucket = var.terraform_state_bucket
    key    = "dev/range/terraform.tfstate"
    region = var.terraform_state_region
  }
}

# ------------------------------------------------------------------------------
# AMI IDs from SSM Parameter Store
# ------------------------------------------------------------------------------

data "aws_ssm_parameter" "kali_ami" {
  name = "/shifter/ami/kali"
}

data "aws_ssm_parameter" "victim_ami" {
  name = "/shifter/ami/ubuntu"
}

data "aws_ssm_parameter" "windows_ami" {
  name = "/shifter/ami/windows"
}

data "aws_ssm_parameter" "dc_ami" {
  name = "/shifter/ami/dc"
}

data "aws_caller_identity" "current" {}

# ------------------------------------------------------------------------------
# KMS CMKs — Secrets Manager and Portal S3 bucket
# ------------------------------------------------------------------------------
# Closes Checkov CKV_AWS_149 (Secrets Manager CMK) and CKV_AWS_145 (S3 SSE-KMS)
# for #213 / #218. The `kms:ViaService` + `kms:CallerAccount` condition is the
# AWS-recommended pattern for service-scoped CMKs: anyone in this account who
# already holds `secretsmanager:GetSecretValue` (or `s3:GetObject`) on the
# specific resource can transparently decrypt through the service; principals
# from other accounts cannot. Annual key rotation is enabled automatically
# (`enable_key_rotation = true`).
#
# These keys are intentionally separate from `engine-state` (Pulumi state) and
# from each other, so a future revoke/rotate of one boundary does not collapse
# the others. See docs/architecture/secrets-manager-cmk-preflight.md and
# docs/architecture/s3-bucket-hardening-preflight.md.

resource "aws_kms_key" "secrets_manager" {
  description             = "CMK for portal Secrets Manager secrets (CKV_AWS_149) — see #213"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableRootAccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        # Account-scoped use via Secrets Manager only, AND bound by encryption
        # context to portal-owned secret ARNs (`shifter-<env>-*` for platform
        # secrets and `shifter/<env>/*` for engine-provisioner runtime secrets).
        # Secrets Manager always passes `SecretARN` as encryption context, so
        # `kms:EncryptionContext:SecretARN` constrains use of this key to the
        # specific secret namespace this CMK is intended to protect — a
        # principal with `kms:Decrypt` could not use this key to decrypt some
        # other Secrets Manager secret in the account.
        Sid       = "AllowPortalSecretsManagerCallers"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey",
          "kms:Encrypt",
          "kms:GenerateDataKey*",
          "kms:ReEncrypt*",
          "kms:CreateGrant",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:CallerAccount" = data.aws_caller_identity.current.account_id
            "kms:ViaService"    = "secretsmanager.${var.aws_region}.amazonaws.com"
          }
          "ForAnyValue:StringLike" = {
            "kms:EncryptionContext:SecretARN" = [
              "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:shifter-${var.environment}-*",
              "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:shifter/${var.environment}/*",
            ]
          }
        }
      },
    ]
  })

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-secrets-manager"
  })
}

resource "aws_kms_alias" "secrets_manager" {
  name          = "alias/shifter-${var.environment}-secrets-manager"
  target_key_id = aws_kms_key.secrets_manager.key_id
}

resource "aws_kms_key" "portal_s3" {
  description             = "CMK for the portal user-uploads S3 bucket (CKV_AWS_145) — see #218"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableRootAccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        # Account-scoped use via S3 only, AND bound by encryption context to
        # objects under the portal user-uploads bucket. S3 always passes
        # `aws:s3:arn = arn:aws:s3:::<bucket>/<key>` as encryption context for
        # SSE-KMS, so this condition constrains use of this key to objects in
        # the configured bucket — a principal with `kms:Decrypt` could not use
        # this key to decrypt some other S3 object in the account.
        Sid       = "AllowPortalUserUploadsBucket"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey",
          "kms:Encrypt",
          "kms:GenerateDataKey*",
          "kms:ReEncrypt*",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:CallerAccount" = data.aws_caller_identity.current.account_id
            "kms:ViaService"    = "s3.${var.aws_region}.amazonaws.com"
          }
          "ForAnyValue:StringLike" = {
            # With S3 Bucket Keys enabled (set in `modules/portal/s3`), S3
            # passes the BUCKET ARN as KMS encryption context for the per-bucket
            # data key. For object-level operations without Bucket Keys S3
            # passes the OBJECT ARN. Allow both patterns so the policy doesn't
            # deny the first SSE-KMS operation.
            "kms:EncryptionContext:aws:s3:arn" = [
              "arn:aws:s3:::${var.user_storage_bucket}",
              "arn:aws:s3:::${var.user_storage_bucket}/*",
            ]
          }
        }
      },
    ]
  })

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-s3"
  })
}

resource "aws_kms_alias" "portal_s3" {
  name          = "alias/shifter-${var.environment}-portal-s3"
  target_key_id = aws_kms_key.portal_s3.key_id
}

resource "aws_kms_key" "redis_at_rest" {
  description             = "CMK for portal Redis (ElastiCache) data-at-rest encryption (CKV_AWS_191) — see #1059"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableRootAccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        # Account-scoped use via ElastiCache only. ElastiCache uses this CMK on
        # the account's behalf — creating grants for the replication group — to
        # encrypt cache storage and the group's automated snapshots. kms:ViaService
        # constrains every use/grant of this key to the ElastiCache service in
        # this region, and kms:CallerAccount pins it to this account. No runtime
        # EC2/ECS role needs a direct decrypt grant: at-rest encryption is
        # provider-owned storage encryption, distinct from the Secrets Manager
        # CMK that protects the Redis AUTH token.
        Sid       = "AllowPortalElastiCacheUse"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey",
          "kms:Encrypt",
          "kms:GenerateDataKey*",
          "kms:ReEncrypt*",
          "kms:CreateGrant",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:CallerAccount" = data.aws_caller_identity.current.account_id
            "kms:ViaService"    = "elasticache.${var.aws_region}.amazonaws.com"
          }
        }
      },
    ]
  })

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-redis-at-rest"
  })
}

resource "aws_kms_alias" "redis_at_rest" {
  name          = "alias/shifter-${var.environment}-redis-at-rest"
  target_key_id = aws_kms_key.redis_at_rest.key_id
}

# ------------------------------------------------------------------------------
# VPC
# ------------------------------------------------------------------------------

module "vpc" {
  source = "../../../modules/portal/vpc"

  name_prefix              = local.name_prefix
  iam_name_prefix          = local.iam_name_prefix
  permissions_boundary_arn = local.ci_role_permissions_boundary_arn
  vpc_cidr                 = var.vpc_cidr
  az_count                 = var.az_count
  enable_nat_gateway       = var.enable_nat_gateway
  tags                     = var.tags

  # Phase 5: VPC Flow Logs
  enable_flow_logs   = var.enable_vpc_flow_logs
  log_retention_days = var.log_retention_days

  # Portal east-west inspection (#122)
  enable_portal_inspection    = var.enable_portal_inspection
  enable_log_aggregation      = var.enable_log_aggregation
  firewall_log_retention_days = var.firewall_log_retention_days

  # Network Firewall lifecycle (mirrors db_deletion_protection root-var / tfvars convention)
  portal_inspection_delete_protection = var.portal_inspection_delete_protection
}

# ------------------------------------------------------------------------------
# RDS PostgreSQL
# ------------------------------------------------------------------------------

module "rds" {
  source = "../../../modules/portal/rds"

  name_prefix              = local.name_prefix
  iam_name_prefix          = local.iam_name_prefix
  permissions_boundary_arn = local.ci_role_permissions_boundary_arn
  secrets_kms_key_arn      = aws_kms_key.secrets_manager.arn
  vpc_id                   = module.vpc.vpc_id
  subnet_ids               = module.vpc.private_subnet_ids
  # Portal RDS is reached by the EKS control plane across the portal<->EKS VPC
  # peering (the portal app + provisioner run as pods in the EKS VPC). The legacy
  # ECS/EC2 runtime that lived in the portal VPC was retired, so ingress is
  # scoped to the peered EKS VPC CIDR rather than an in-VPC security group.
  allowed_cidr_blocks = [var.eks_vpc_cidr]

  db_name               = var.db_name
  db_username           = var.db_username
  engine_version        = var.db_engine_version
  ca_cert_identifier    = var.db_ca_cert_identifier
  instance_class        = var.db_instance_class
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_max_allocated_storage
  multi_az              = var.db_multi_az
  backup_retention_days = var.db_backup_retention_days
  deletion_protection   = var.db_deletion_protection
  skip_final_snapshot   = var.db_skip_final_snapshot
  apply_immediately     = var.db_apply_immediately

  # Phase 5: RDS Log Exports
  enable_log_exports = var.enable_rds_log_exports
  log_retention_days = var.log_retention_days

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Redis (for Django Channels)
# ------------------------------------------------------------------------------

module "redis" {
  source = "../../../modules/portal/redis"

  name_prefix     = local.name_prefix
  iam_name_prefix = local.iam_name_prefix
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.private_subnet_ids
  # Reached by the EKS control plane over the portal<->EKS VPC peering; scoped to
  # the peered EKS VPC CIDR (see the RDS module note above).
  allowed_cidr_blocks = [var.eks_vpc_cidr]
  node_type           = var.redis_node_type
  engine_version      = var.redis_engine_version
  enable_replication  = var.redis_enable_replication
  apply_immediately   = var.redis_apply_immediately

  # AUTH + in-transit encryption (#938): the AUTH token secret is encrypted by
  # the portal CMK. is_active_channel_backend rejects a live channel layer on
  # the plaintext single-node path. redis_at_rest_kms_key_arn is the dedicated
  # data-at-rest CMK for the replication group (#1059).
  secrets_kms_key_arn         = aws_kms_key.secrets_manager.arn
  redis_at_rest_kms_key_arn   = aws_kms_key.redis_at_rest.arn
  cloudwatch_logs_kms_key_arn = aws_kms_key.cloudwatch_logs.arn
  permissions_boundary_arn    = local.ci_role_permissions_boundary_arn
  is_active_channel_backend   = var.enable_redis

  # Automatic Redis AUTH rotation (#159) is left off: it required a refreshable
  # ASG to roll consumers to the new token, and the legacy ECS/EC2 runtime is
  # retired. Re-wiring rotation to roll EKS pods is tracked separately.

  # CloudWatch Alarms
  enable_alarms = var.alarm_email != ""
  alarm_actions = var.alarm_email != "" ? [aws_sns_topic.alerts.arn] : []

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Cognito
# ------------------------------------------------------------------------------

module "cognito" {
  source = "../../../modules/portal/cognito"

  name_prefix              = local.name_prefix
  iam_name_prefix          = local.iam_name_prefix
  permissions_boundary_arn = local.ci_role_permissions_boundary_arn
  environment              = var.environment
  aws_region               = var.aws_region
  log_retention_days       = var.log_retention_days
  secrets_kms_key_arn      = aws_kms_key.secrets_manager.arn
  cognito_domain_prefix    = var.cognito_domain_prefix
  callback_urls            = ["https://${var.domain_name}/oidc/callback/"]
  logout_urls              = ["https://${var.domain_name}/"]
  allowed_email_domains    = var.allowed_email_domains
  allowed_emails           = var.allowed_emails

  # Client-secret rotation (#159): operator-triggered Lambda + scheduled email
  # reminder. The ASG-refresh hook is gone with the legacy runtime; EKS consumers
  # pick up a rotated client on their next pod roll.
  alerts_topic_arn         = aws_sns_topic.alerts.arn
  enable_rotation_reminder = var.alarm_email != ""
  deletion_protection      = false

  # Dev: longer token validity for less frequent MFA prompts
  access_token_validity_hours = 8
  id_token_validity_hours     = 8

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Shared Alerting SNS Topic
# ------------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name              = "${local.name_prefix}-alerts"
  kms_master_key_id = "alias/aws/sns"
  tags              = var.tags
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count = var.alarm_email != "" ? 1 : 0

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ------------------------------------------------------------------------------
# Backup-Failure Alerting (#160)
# ------------------------------------------------------------------------------
# RDS reports backup/snapshot failures as RDS events, delivered through an RDS
# event subscription to a CMK-encrypted SNS topic. This cannot reuse the shared
# `aws_sns_topic.alerts` above (AWS-managed key cannot grant the RDS service
# principal), so the module owns a dedicated CMK + topic. See
# docs/ops/disaster-recovery.md.

module "backup_alerts" {
  source = "../../../modules/portal/backup-alerts"

  name_prefix = local.name_prefix
  environment = var.environment
  alarm_email = var.alarm_email

  db_instance_identifiers = compact([
    module.rds.db_instance_id,
  ])

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Messaging (SNS/SQS)
# ------------------------------------------------------------------------------

module "messaging" {
  source = "../../../modules/portal/messaging"

  name_prefix                = local.name_prefix
  tags                       = var.tags
  consumers                  = var.messaging_consumers
  visibility_timeout_seconds = var.messaging_visibility_timeout_seconds
  message_retention_seconds  = var.messaging_message_retention_seconds

  # Dead Letter Queue
  enable_dlq                    = var.messaging_enable_dlq
  dlq_max_receive_count         = var.messaging_dlq_max_receive_count
  dlq_message_retention_seconds = var.messaging_dlq_message_retention_seconds

  # CloudWatch Alarms
  enable_alarms               = var.messaging_enable_alarms
  alarm_queue_depth_threshold = var.messaging_alarm_queue_depth_threshold
  alarm_message_age_threshold = var.messaging_alarm_message_age_threshold
  alarm_dlq_threshold         = var.messaging_alarm_dlq_threshold
  alarm_actions               = var.alarm_email != "" ? [aws_sns_topic.alerts.arn] : []
}

# ------------------------------------------------------------------------------
# SSM Deployment (Parameter Store + SSM Document)
# ------------------------------------------------------------------------------

module "ssm" {
  source = "../../../modules/portal/ssm"

  environment    = var.environment
  cloud_provider = var.cloud_provider
  name_prefix    = local.name_prefix
  aws_region     = var.aws_region
  tags           = var.tags

  # ECR configuration
  ecr_registry        = split("/", data.terraform_remote_state.foundation.outputs.portal_ecr_url)[0]
  ecr_repository_name = split("/", data.terraform_remote_state.foundation.outputs.portal_ecr_url)[1]

  # Secrets Manager ARNs
  db_secret_arn      = module.rds.db_credentials_secret_arn
  app_secret_arn     = aws_secretsmanager_secret.app.arn
  cognito_secret_arn = module.cognito.cognito_secret_arn

  # Application configuration
  domain_name       = var.domain_name
  s3_bucket_name    = var.user_storage_bucket
  ctfd_platform_url = var.enable_ctfd ? "${module.ctfd[0].url}/login" : ""
  ctf_content_bucket_name = (
    var.ctf_content_bucket_arn == ""
    ? ""
    : trimprefix(var.ctf_content_bucket_arn, "arn:aws:s3:::")
  )
  ctf_content_prefix    = var.ctf_content_prefix
  ctf_content_max_bytes = var.ctf_content_max_bytes

  # Messaging configuration
  sqs_cms_url    = module.messaging.sqs_queue_urls["cms"]
  sqs_engine_url = module.messaging.sqs_queue_urls["engine"]
  sqs_mc_url     = module.messaging.sqs_queue_urls["mc"]

  range_events_topic_id = module.messaging.sns_topic_arn
  # Redis wiring is environment-owned and decoupled from autoscaling (ADR-018, #849).
  redis_endpoint = var.enable_redis ? module.redis.redis_endpoint : ""
  enable_redis   = var.enable_redis
  # AUTH + in-transit encryption references (#938). Non-secret: the token stays
  # in Secrets Manager and is hydrated into REDIS_PASSWORD by entrypoint.sh.
  redis_secret_arn = module.redis.redis_secret_arn
  redis_tls        = module.redis.redis_tls_enabled
  redis_ca_mode    = "system"

  # Database endpoint (direct RDS connection - hostname only, not endpoint with port)
  db_host_override        = module.rds.db_instance_address
  enable_db_host_override = true

  # Logging level (DEBUG for dev, INFO for prod)
  log_level = var.log_level

  # Email configuration
  email_backend  = var.email_backend
  ctf_from_email = var.ctf_from_email

  # Portal runtime capacity tunables (#930). Worker count is sized to the
  # instance vCPU budget; terminal caps are process-local, so the per-instance
  # ceiling is portal_web_workers * terminal_max_sessions.
  portal_web_workers             = var.portal_web_workers
  terminal_max_sessions          = var.terminal_max_sessions
  terminal_max_sessions_per_user = var.terminal_max_sessions_per_user

  terminal_idle_timeout_seconds = var.terminal_idle_timeout_seconds
  terminal_max_session_seconds  = var.terminal_max_session_seconds
  terminal_read_poll_seconds    = var.terminal_read_poll_seconds

  # Portal web capacity metrics (#940). Enable flag and busy-ratio denominator
  # are env-owned and hydrated by both first-boot user_data and SSM redeploy.
  portal_capacity_metrics_enabled = var.portal_capacity_metrics_enabled
  portal_worker_soft_concurrency  = var.portal_worker_soft_concurrency
}

# ------------------------------------------------------------------------------
# CTFd
# ------------------------------------------------------------------------------

module "ctfd" {
  count = var.enable_ctfd ? 1 : 0

  source = "../../../modules/portal/ctfd"

  aws_region               = var.aws_region
  name_prefix              = local.name_prefix
  iam_name_prefix          = local.iam_name_prefix
  permissions_boundary_arn = local.ci_role_permissions_boundary_arn
  vpc_id                   = module.vpc.vpc_id
  # Public-workload tier, kept out of the ALB ingress CIDR so CTFd cannot
  # reach Django:8000 / Guacamole:8080 directly (#911 NET-2 / #933).
  subnet_id = module.vpc.public_workload_subnet_ids[0]

  ami_id                 = var.ctfd_ami_id
  instance_type          = var.ctfd_instance_type
  root_volume_size       = var.ctfd_root_volume_size
  root_volume_type       = var.ctfd_root_volume_type
  root_volume_iops       = var.ctfd_root_volume_iops
  root_volume_throughput = var.ctfd_root_volume_throughput

  domain                 = var.ctfd_domain
  ctfd_repo_url          = var.ctfd_repo_url
  ctfd_git_ref           = var.ctfd_git_ref
  docker_compose_version = var.ctfd_docker_compose_version
  docker_buildx_version  = var.ctfd_docker_buildx_version
  ssh_public_key         = var.ctfd_ssh_public_key
  ssh_allowed_cidrs      = var.ctfd_ssh_allowed_cidrs

  tags = var.tags
}

# ------------------------------------------------------------------------------
# S3 User Storage
# ------------------------------------------------------------------------------

module "s3" {
  source = "../../../modules/portal/s3"

  bucket_name          = var.user_storage_bucket
  cors_allowed_origins = ["https://${var.domain_name}"]
  kms_key_arn          = aws_kms_key.portal_s3.arn
  tags                 = var.tags
}

resource "aws_iam_role_policy" "range_instance_portal_s3_kms_read" {
  name = "portal-s3-kms-read"
  role = replace(data.terraform_remote_state.range.outputs.range_instance_role_arn, "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/", "")

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = aws_kms_key.portal_s3.arn
        Condition = {
          StringEquals = {
            "kms:CallerAccount" = data.aws_caller_identity.current.account_id
            "kms:ViaService"    = "s3.${var.aws_region}.amazonaws.com"
          }
        }
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# App Secret (Django secret key)
# ------------------------------------------------------------------------------

resource "random_password" "django_secret_key" {
  length  = 50
  special = true
}

# Fernet encryption key for django-encrypted-model-fields (32 bytes, base64-encoded)
resource "random_id" "field_encryption_key" {
  byte_length = 32
}

resource "aws_secretsmanager_secret" "app" {
  name                    = "shifter-${local.name_prefix}-app"
  description             = "Django application secrets"
  recovery_window_in_days = 0 # NOSONAR - dev environment: immediate deletion avoids naming conflicts on recreate
  kms_key_id              = aws_kms_key.secrets_manager.arn

  tags = merge(var.tags, {
    Name = "shifter-${local.name_prefix}-app"
  })
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    django_secret_key    = random_password.django_secret_key.result
    field_encryption_key = local.field_encryption_key_padded
  })
}

# ------------------------------------------------------------------------------
# Domain Controller domain Administrator password (DC_DOMAIN_PASSWORD)
# ------------------------------------------------------------------------------
# Deployment-scoped secret the provisioner uses to promote each prebaked DC AMI
# and domain-join victims. Relocated here from the retired engine-provisioner
# (ECS) module; the EKS provisioner reads it by name at runtime (hydrated, not
# forwarded in the plain env), so the stable name is preserved. Encrypted by the
# portal secrets CMK, same pattern as the app + RDS credentials. Cleartext lives
# only in Secrets Manager and Terraform state. Rotate with:
#   terraform apply -replace='random_password.dc_domain_password'
# then re-promote affected DCs (or let the next range provision pick it up).
resource "random_password" "dc_domain_password" {
  length  = 24
  special = true
  # Symbol set restricted to characters that survive PowerShell / shell
  # interpolation in the DC bootstrap path while still meeting Windows AD
  # complexity (length + character classes guarantee coverage in practice).
  override_special = "!@#%^&*()-_=+[]{}:?"
}

resource "aws_secretsmanager_secret" "dc_domain_password" {
  name                    = "shifter-${var.environment}-portal-dc-domain"
  description             = "Domain Controller domain Administrator password (DC_DOMAIN_PASSWORD)"
  recovery_window_in_days = 0 # NOSONAR - matches the other portal secrets: immediate deletion avoids naming conflicts on recreate
  kms_key_id              = aws_kms_key.secrets_manager.arn

  tags = merge(var.tags, {
    Name = "shifter-${var.environment}-portal-dc-domain"
  })
}

resource "aws_secretsmanager_secret_version" "dc_domain_password" {
  secret_id     = aws_secretsmanager_secret.dc_domain_password.id
  secret_string = random_password.dc_domain_password.result
}

# ------------------------------------------------------------------------------
# VPC Peering: Portal <-> Range
# Enables SSH connectivity from Portal to Range instances for Terminal UI
# ------------------------------------------------------------------------------

resource "aws_vpc_peering_connection" "portal_to_range" {
  vpc_id      = module.vpc.vpc_id
  peer_vpc_id = data.terraform_remote_state.range.outputs.vpc_id
  auto_accept = true # Same account, same region

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-to-range-peering"
  })
}

# Route from Portal private subnets to Range VPC via peering (per-AZ).
resource "aws_route" "portal_to_range" {
  count = length(module.vpc.private_route_table_ids)

  route_table_id            = module.vpc.private_route_table_ids[count.index]
  destination_cidr_block    = data.terraform_remote_state.range.outputs.vpc_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.portal_to_range.id
}

# Route from Range private subnets to Portal VPC via peering
resource "aws_route" "range_to_portal" {
  route_table_id            = data.terraform_remote_state.range.outputs.private_route_table_id
  destination_cidr_block    = module.vpc.vpc_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.portal_to_range.id
}

# Note: SSH rules from Portal to Kali/Victim are defined in the range VPC module
# (terraform/modules/range/vpc/main.tf) using the portal_vpc_cidr variable.
# Do not duplicate them here.

# ------------------------------------------------------------------------------
# SES (Transactional Email)
# ------------------------------------------------------------------------------

module "ses" {
  source = "../../../modules/portal/ses"

  domain = var.ses_domain
}

# ------------------------------------------------------------------------------
# Log Aggregation (S3, SQS, Firehose for internal observability)
# Note: XDR CloudTrail integration is managed via CloudFormation, not Terraform
# ------------------------------------------------------------------------------

module "log_aggregation" {
  source = "../../../modules/log-aggregation"

  name_prefix              = local.name_prefix
  iam_name_prefix          = local.iam_name_prefix
  permissions_boundary_arn = local.ci_role_permissions_boundary_arn
  environment              = var.environment
  aws_region               = var.aws_region
  log_retention_days       = var.log_retention_days
  enable_log_aggregation   = var.enable_log_aggregation

  # Phase 5: ALB and WAF logging
  enable_alb_access_logs = var.enable_alb_access_logs
  enable_waf_logging     = var.enable_waf_logging

  # Log group sources (for CloudWatch subscription filters)
  source_log_group_names = var.enable_log_aggregation ? concat(
    [module.cognito.log_group_name],
    # Phase 5: VPC flow logs and RDS logs
    var.enable_vpc_flow_logs ? [module.vpc.flow_logs_log_group_name] : [],
    var.enable_rds_log_exports ? module.rds.log_group_names : [],
    # Portal east-west inspection (#122)
    var.enable_portal_inspection ? [module.vpc.firewall_log_group_name] : [],
  ) : []

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Bedrock Model Invocation Logging
# Captures invocation details including errors for debugging
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "bedrock" {
  count = var.enable_bedrock_logging ? 1 : 0

  name              = "/aws/bedrock/${local.name_prefix}-invocations"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.cloudwatch_logs.arn

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-bedrock-invocations"
  })
}

resource "aws_iam_role" "bedrock_logging" {
  count = var.enable_bedrock_logging ? 1 : 0

  name = "${local.iam_name_prefix}-bedrock-logging"

  permissions_boundary = local.ci_role_permissions_boundary_arn

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "bedrock.amazonaws.com"
      }
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "bedrock_logging" {
  count = var.enable_bedrock_logging ? 1 : 0

  name = "cloudwatch-logs"
  role = aws_iam_role.bedrock_logging[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ]
      Resource = "${aws_cloudwatch_log_group.bedrock[0].arn}:*"
    }]
  })
}

resource "aws_bedrock_model_invocation_logging_configuration" "this" {
  count = var.enable_bedrock_logging ? 1 : 0

  logging_config {
    embedding_data_delivery_enabled = false
    image_data_delivery_enabled     = false
    text_data_delivery_enabled      = true

    cloudwatch_config {
      log_group_name = aws_cloudwatch_log_group.bedrock[0].name
      role_arn       = aws_iam_role.bedrock_logging[0].arn
    }
  }
}
