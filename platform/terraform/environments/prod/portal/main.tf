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
  name_prefix                 = "${var.environment}-portal"
  alb_access_logs_bucket_name = "${local.name_prefix}-alb-logs-${var.environment}-${data.aws_caller_identity.current.account_id}"
  # Add padding to field_encryption_key (b64_url doesn't include padding, but Fernet requires it)
  field_encryption_key_padded = "${random_id.field_encryption_key.b64_url}="
}

# ------------------------------------------------------------------------------
# Remote State - Foundation (ECR)
# ------------------------------------------------------------------------------

data "terraform_remote_state" "foundation" {
  backend = "s3"
  config = {
    bucket = "shifter-infra-c0045c36-4e43-4710-9a2e-ce8534cb5851"
    key    = "shifter/prod/terraform.tfstate"
    region = "us-east-2"
  }
}

# ------------------------------------------------------------------------------
# Remote State - Range VPC
# ------------------------------------------------------------------------------

data "terraform_remote_state" "range" {
  backend = "s3"
  config = {
    bucket = "shifter-infra-c0045c36-4e43-4710-9a2e-ce8534cb5851"
    key    = "prod/range/terraform.tfstate"
    region = "us-east-2"
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

# ------------------------------------------------------------------------------
# VPC
# ------------------------------------------------------------------------------

module "vpc" {
  source = "../../../modules/portal/vpc"

  name_prefix        = local.name_prefix
  vpc_cidr           = var.vpc_cidr
  az_count           = var.az_count
  enable_nat_gateway = var.enable_nat_gateway
  tags               = var.tags

  # Phase 5: VPC Flow Logs
  enable_flow_logs   = var.enable_vpc_flow_logs
  log_retention_days = var.log_retention_days

  # Portal east-west inspection (#122)
  enable_portal_inspection    = var.enable_portal_inspection
  enable_log_aggregation      = var.enable_log_aggregation
  firewall_log_retention_days = var.firewall_log_retention_days
}

# ------------------------------------------------------------------------------
# RDS PostgreSQL
# ------------------------------------------------------------------------------

module "rds" {
  source = "../../../modules/portal/rds"

  name_prefix                = local.name_prefix
  secrets_kms_key_arn        = aws_kms_key.secrets_manager.arn
  vpc_id                     = module.vpc.vpc_id
  subnet_ids                 = module.vpc.private_subnet_ids
  allowed_security_group_ids = [module.ec2.security_group_id]

  db_name               = var.db_name
  db_username           = var.db_username
  engine_version        = var.db_engine_version
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
# ALB (created first, target attached after EC2)
# ------------------------------------------------------------------------------

module "alb" {
  source = "../../../modules/portal/alb"

  name_prefix                = local.name_prefix
  vpc_id                     = module.vpc.vpc_id
  public_subnet_ids          = module.vpc.public_subnet_ids
  domain_name                = var.domain_name
  app_port                   = var.app_port
  health_check_path          = var.health_check_path
  enable_stickiness          = var.enable_autoscaling
  enable_deletion_protection = true # prod: secure default; flip false + apply before any intentional destroy

  # Phase 5: ALB Access Logs and WAF Logging
  enable_access_logs      = var.enable_alb_access_logs
  logs_bucket_name        = var.enable_alb_access_logs ? local.alb_access_logs_bucket_name : ""
  logs_bucket_policy_id   = var.enable_alb_access_logs ? module.log_aggregation.alb_logs_bucket_policy_id : ""
  enable_waf_logging      = var.enable_waf_logging
  waf_log_destination_arn = var.enable_waf_logging ? module.log_aggregation.waf_firehose_arn : ""

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Redis (for Django Channels in ASG mode)
# ------------------------------------------------------------------------------

module "redis" {
  source = "../../../modules/portal/redis"

  name_prefix                = local.name_prefix
  vpc_id                     = module.vpc.vpc_id
  subnet_ids                 = module.vpc.private_subnet_ids
  allowed_security_group_ids = [module.ec2.security_group_id]
  node_type                  = var.redis_node_type
  engine_version             = var.redis_engine_version
  enable_replication         = var.redis_enable_replication

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

  name_prefix           = local.name_prefix
  environment           = var.environment
  aws_region            = var.aws_region
  log_retention_days    = var.log_retention_days
  secrets_kms_key_arn   = aws_kms_key.secrets_manager.arn
  cognito_domain_prefix = var.cognito_domain_prefix
  callback_urls         = ["https://${var.domain_name}/oidc/callback/"]
  logout_urls           = ["https://${var.domain_name}/"]
  allowed_email_domains = var.allowed_email_domains
  allowed_emails        = var.allowed_emails
  deletion_protection   = true

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

  environment = var.environment
  name_prefix = local.name_prefix
  aws_region  = var.aws_region
  tags        = var.tags

  # ECR configuration
  ecr_registry        = split("/", data.terraform_remote_state.foundation.outputs.portal_ecr_url)[0]
  ecr_repository_name = split("/", data.terraform_remote_state.foundation.outputs.portal_ecr_url)[1]

  # Secrets Manager ARNs
  db_secret_arn                 = module.rds.db_credentials_secret_arn
  app_secret_arn                = aws_secretsmanager_secret.app.arn
  cognito_secret_arn            = module.cognito.cognito_secret_arn
  guacamole_secret_arn          = module.guacamole.json_auth_secret_arn
  guacamole_base_url            = "https://${var.domain_name}/guacamole"
  guacamole_api_base_url        = module.guacamole.guacamole_client_internal_url
  dc_domain_password_secret_arn = module.engine_provisioner.dc_domain_password_secret_arn

  # Application configuration
  domain_name    = var.domain_name
  s3_bucket_name = var.user_storage_bucket

  # Engine provisioner configuration
  engine_ecs_cluster_arn        = module.engine_provisioner.ecs_cluster_arn
  engine_task_definition_family = module.engine_provisioner.task_definition_family
  engine_ecs_security_group_id  = module.engine_provisioner.ecs_security_group_id
  engine_private_subnet_ids     = join(",", module.vpc.private_subnet_ids)

  # Messaging configuration
  sqs_cms_url    = module.messaging.sqs_queue_urls["cms"]
  sqs_engine_url = module.messaging.sqs_queue_urls["engine"]
  sqs_mc_url     = module.messaging.sqs_queue_urls["mc"]
  # Redis wiring is environment-owned and decoupled from autoscaling (ADR-018, #849).
  redis_endpoint = var.enable_redis ? module.redis.redis_endpoint : ""
  enable_redis   = var.enable_redis

  # Database endpoint (direct RDS connection - hostname only, not endpoint with port)
  db_host_override        = module.rds.db_instance_address
  enable_db_host_override = true

  # Logging level (DEBUG for dev, INFO for prod)
  log_level = var.log_level

  # Email configuration
  email_backend  = var.email_backend
  ctf_from_email = var.ctf_from_email
}

# ------------------------------------------------------------------------------
# EC2
# ------------------------------------------------------------------------------

module "ec2" {
  source = "../../../modules/portal/ec2"

  aws_region            = var.aws_region
  ec2_ami_id            = var.ec2_ami_id
  name_prefix           = local.name_prefix
  vpc_id                = module.vpc.vpc_id
  subnet_id             = module.vpc.private_subnet_ids[0]
  alb_security_group_id = module.alb.security_group_id
  instance_type         = var.ec2_instance_type
  ecr_repository_arn    = data.terraform_remote_state.foundation.outputs.portal_ecr_arn
  ecr_repository_url    = data.terraform_remote_state.foundation.outputs.portal_ecr_url
  secret_arns = [
    module.rds.db_credentials_secret_arn,
    aws_secretsmanager_secret.app.arn,
    module.cognito.cognito_secret_arn,
    module.guacamole.json_auth_secret_arn,
    module.engine_provisioner.dc_domain_password_secret_arn,
  ]
  secrets_manager_kms_key_arn = aws_kms_key.secrets_manager.arn
  s3_bucket_arn               = module.s3.bucket_arn
  app_port                    = var.app_port
  root_volume_size            = var.ec2_root_volume_size

  # ECS permissions for engine provisioner
  ecs_cluster_arn            = module.engine_provisioner.ecs_cluster_arn
  ecs_task_definition_family = module.engine_provisioner.task_definition_family
  ecs_task_role_arn          = module.engine_provisioner.ecs_task_role_arn
  ecs_execution_role_arn     = module.engine_provisioner.ecs_execution_role_arn

  # Autoscaling configuration
  enable_autoscaling   = var.enable_autoscaling
  subnet_ids           = module.vpc.private_subnet_ids
  target_group_arn     = module.alb.target_group_arn
  asg_min_size         = var.asg_min_size
  asg_max_size         = var.asg_max_size
  asg_desired_capacity = var.asg_desired_capacity
  redis_endpoint       = var.enable_redis ? module.redis.redis_endpoint : ""
  scale_up_threshold   = var.scale_up_threshold
  scale_down_threshold = var.scale_down_threshold
  log_retention_days   = var.log_retention_days

  # Messaging
  sqs_queue_arns  = values(module.messaging.sqs_queue_arns)
  sqs_queue_urls  = module.messaging.sqs_queue_urls
  sqs_kms_key_arn = module.messaging.kms_key_arn

  # Parameter Store prefix for user_data bootstrap
  ssm_parameter_store_prefix = module.ssm.parameter_store_prefix

  # SES
  ses_domain_identity_arn = module.ses.domain_identity_arn
  enable_ses              = true

  tags = var.tags

  # First boot installs Docker and configures ECR/SSM-backed deployment. Make
  # the portal AWS service endpoints part of the VPC dependency boundary so a
  # fresh account does not race private AWS API reachability.
  depends_on = [module.vpc]
}

# ------------------------------------------------------------------------------
# ALB Target Attachment (single instance mode only - ASG attaches automatically)
# ------------------------------------------------------------------------------

resource "aws_lb_target_group_attachment" "portal" {
  count = var.enable_autoscaling ? 0 : 1

  target_group_arn = module.alb.target_group_arn
  target_id        = module.ec2.instance_id
  port             = var.app_port
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
  recovery_window_in_days = 7
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
# Engine Provisioner (ECS Fargate)
# Note: Defined before log_aggregation so its log groups can be included
# ------------------------------------------------------------------------------

module "engine_provisioner" {
  source = "../../../modules/engine-provisioner"

  name_prefix                 = local.name_prefix
  environment                 = var.environment
  tags                        = var.tags
  log_retention_days          = var.log_retention_days
  secrets_manager_kms_key_arn = aws_kms_key.secrets_manager.arn

  # ECR
  ecr_repository_url  = data.terraform_remote_state.foundation.outputs.engine_provisioner_ecr_url
  container_image_tag = var.engine_container_tag

  # Networking (Portal VPC for RDS access)
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids

  # Database (direct RDS connection - hostname only, port passed separately)
  db_host        = module.rds.db_instance_address
  db_port        = 5432
  db_name        = var.db_name
  db_resource_id = module.rds.db_resource_id

  # RDS security group (for adding ingress rule)
  rds_security_group_id = module.rds.db_security_group_id

  # Engine state (from Range environment)
  engine_state_bucket          = data.terraform_remote_state.range.outputs.engine_state_bucket_name
  engine_state_bucket_arn      = data.terraform_remote_state.range.outputs.engine_state_bucket_arn
  engine_locks_table           = data.terraform_remote_state.range.outputs.engine_locks_table_name
  engine_locks_table_arn       = data.terraform_remote_state.range.outputs.engine_locks_table_arn
  engine_secrets_kms_key_arn   = data.terraform_remote_state.range.outputs.engine_secrets_kms_key_arn
  engine_secrets_kms_key_alias = data.terraform_remote_state.range.outputs.engine_secrets_kms_key_alias

  # Range VPC configuration
  range_vpc_id                = data.terraform_remote_state.range.outputs.vpc_id
  range_vpc_cidr              = data.terraform_remote_state.range.outputs.vpc_cidr
  range_route_table_id        = data.terraform_remote_state.range.outputs.private_route_table_id
  range_availability_zone     = data.terraform_remote_state.range.outputs.availability_zone
  range_instance_profile_arn  = data.terraform_remote_state.range.outputs.range_instance_profile_arn
  range_instance_profile_name = data.terraform_remote_state.range.outputs.range_instance_profile_name
  range_instance_role_arn     = data.terraform_remote_state.range.outputs.range_instance_role_arn

  # AMIs (from SSM Parameter Store)
  kali_ami_id    = data.aws_ssm_parameter.kali_ami.value
  victim_ami_id  = data.aws_ssm_parameter.victim_ami.value
  windows_ami_id = data.aws_ssm_parameter.windows_ami.value
  dc_ami_id      = data.aws_ssm_parameter.dc_ami.value

  # Prebaked DC configuration. dc_domain_password is sourced from
  # aws_secretsmanager_secret.dc_domain_password inside the
  # engine-provisioner module; no plaintext input from this stack.
  dc_domain_name = var.dc_domain_name

  # Instance types
  kali_instance_type   = var.kali_instance_type
  victim_instance_type = var.victim_instance_type

  # S3
  agent_s3_bucket           = module.s3.bucket_name
  agent_s3_bucket_arn       = module.s3.bucket_arn
  s3_endpoint_id            = try(data.terraform_remote_state.range.outputs.s3_endpoint_id, "")
  firewall_endpoint_id      = data.terraform_remote_state.range.outputs.firewall_endpoint_id != null ? data.terraform_remote_state.range.outputs.firewall_endpoint_id : ""
  ssm_endpoints_subnet_cidr = try(data.terraform_remote_state.range.outputs.ssm_endpoints_subnet_cidr, "")

  # Portal VPC configuration (for terminal SSH routing)
  portal_vpc_cidr       = module.vpc.vpc_cidr
  portal_vpc_peering_id = aws_vpc_peering_connection.portal_to_range.id

  # NGFW (VM-Series) - from Range VPC outputs
  ngfw_mgmt_security_group_id = data.terraform_remote_state.range.outputs.ngfw_mgmt_security_group_id != null ? data.terraform_remote_state.range.outputs.ngfw_mgmt_security_group_id : ""
  ngfw_data_security_group_id = data.terraform_remote_state.range.outputs.ngfw_data_security_group_id != null ? data.terraform_remote_state.range.outputs.ngfw_data_security_group_id : ""
  ngfw_ami_id                 = data.terraform_remote_state.range.outputs.vm_series_ami_id
  ngfw_instance_type          = data.terraform_remote_state.range.outputs.vm_series_instance_type
  ngfw_subnet_id              = data.terraform_remote_state.range.outputs.ngfw_subnet_id != null ? data.terraform_remote_state.range.outputs.ngfw_subnet_id : ""
  ngfw_subnet_cidr            = data.terraform_remote_state.range.outputs.ngfw_subnet_cidr != null ? data.terraform_remote_state.range.outputs.ngfw_subnet_cidr : ""
  ngfw_instance_profile_name  = data.terraform_remote_state.range.outputs.ngfw_instance_profile_name != null ? data.terraform_remote_state.range.outputs.ngfw_instance_profile_name : ""
  ngfw_instance_role_arn      = data.terraform_remote_state.range.outputs.ngfw_instance_role_arn != null ? data.terraform_remote_state.range.outputs.ngfw_instance_role_arn : ""

  # Messaging (SNS topic for range event publishing)
  sns_topic_arn   = module.messaging.sns_topic_arn
  sns_kms_key_arn = module.messaging.kms_key_arn

  # Alarms
  enable_alarms = true
  alarm_email   = var.alarm_email

  depends_on = [module.vpc]
}

moved {
  from = module.pulumi_provisioner
  to   = module.engine_provisioner
}

# ------------------------------------------------------------------------------
# Guacamole (Remote Desktop Gateway)
# ------------------------------------------------------------------------------

module "guacamole" {
  source = "../../../modules/guacamole"

  name_prefix         = local.name_prefix
  environment         = var.environment
  tags                = var.tags
  secrets_kms_key_arn = aws_kms_key.secrets_manager.arn

  # Networking (Portal VPC)
  vpc_id                   = module.vpc.vpc_id
  private_subnet_ids       = module.vpc.private_subnet_ids
  range_vpc_cidr           = data.terraform_remote_state.range.outputs.vpc_cidr
  portal_security_group_id = module.ec2.security_group_id
  enable_portal_sg_rule    = true

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
  guacd_image_tag                = var.guacd_image_tag
  guacamole_client_image_tag     = var.guacamole_client_image_tag
  guacd_cpu                      = var.guacd_cpu
  guacd_memory                   = var.guacd_memory
  guacamole_client_cpu           = var.guacamole_client_cpu
  guacamole_client_memory        = var.guacamole_client_memory
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
  db_apply_immediately     = var.guacamole_db_apply_immediately

  # Autoscaling
  enable_autoscaling       = var.guacamole_enable_autoscaling
  autoscaling_min_capacity = var.guacamole_autoscaling_min_capacity
  autoscaling_max_capacity = var.guacamole_autoscaling_max_capacity
  autoscaling_cpu_target   = var.guacamole_autoscaling_cpu_target

  # Secrets
  secrets_recovery_window_days = var.guacamole_secrets_recovery_window_days

  # OIDC/Cognito authentication
  enable_oidc          = var.guacamole_enable_oidc
  cognito_user_pool_id = module.cognito.user_pool_id
  cognito_domain       = module.cognito.cognito_domain
  aws_region           = var.aws_region
  domain_name          = var.domain_name

  depends_on = [module.vpc]
}

# ALB health checks and user traffic are routed through the portal inspection
# boundary before they reach private targets. Source security group references
# do not survive that middlebox path reliably, so keep those existing SG rules
# and add CIDR-scoped ingress from only the ALB public subnet CIDRs.
resource "aws_security_group_rule" "portal_app_from_alb_subnets" {
  type              = "ingress"
  from_port         = var.app_port
  to_port           = var.app_port
  protocol          = "tcp"
  cidr_blocks       = module.vpc.public_subnet_cidrs
  security_group_id = module.ec2.security_group_id
  description       = "HTTP from ALB public subnets through inspection"
}

resource "aws_security_group_rule" "guacamole_client_from_alb_subnets" {
  type              = "ingress"
  from_port         = 8080
  to_port           = 8080
  protocol          = "tcp"
  cidr_blocks       = module.vpc.public_subnet_cidrs
  security_group_id = module.guacamole.guacamole_client_security_group_id
  description       = "HTTP from ALB public subnets through inspection"
}

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

  name_prefix            = local.name_prefix
  environment            = var.environment
  aws_region             = var.aws_region
  log_retention_days     = var.log_retention_days
  enable_log_aggregation = var.enable_log_aggregation

  # Phase 5: ALB and WAF logging
  enable_alb_access_logs = var.enable_alb_access_logs
  enable_waf_logging     = var.enable_waf_logging

  # Log group sources (for CloudWatch subscription filters)
  source_log_group_names = var.enable_log_aggregation ? concat(
    [module.ec2.log_group_name],
    [module.cognito.log_group_name],
    # Phase 5: VPC flow logs and RDS logs
    var.enable_vpc_flow_logs ? [module.vpc.flow_logs_log_group_name] : [],
    var.enable_rds_log_exports ? module.rds.log_group_names : [],
    # Engine provisioner logs
    module.engine_provisioner.log_group_names,
    # Guacamole logs
    module.guacamole.log_group_names,
    # Portal east-west inspection (#122)
    var.enable_portal_inspection ? [module.vpc.firewall_log_group_name] : [],
  ) : []

  # Monitoring
  enable_alarms = true
  alarm_email   = var.alarm_email

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

  name = "${local.name_prefix}-bedrock-logging"

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
