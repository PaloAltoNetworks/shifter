# SSM Module - Portal Deployment
#
# Creates Parameter Store parameters for deployment configuration.
# These parameters are read by:
# - user_data.sh (ASG instance bootstrap)
# - CI/CD workflow inline deploy script

data "aws_caller_identity" "current" {}

locals {
  common_tags = merge(var.tags, {
    Module = "ssm"
  })

  # Parameter Store path prefix
  ps_prefix = "/shifter/${var.environment}/portal"
}

# ------------------------------------------------------------------------------
# Parameter Store - Deployment Configuration
# ------------------------------------------------------------------------------

resource "aws_ssm_parameter" "image_tag" {
  name        = "${local.ps_prefix}/image-tag"
  description = "Current Docker image tag for portal deployment"
  type        = "String"
  value       = var.initial_image_tag

  tags = local.common_tags

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "ecr_registry" {
  name        = "${local.ps_prefix}/ecr-registry"
  description = "ECR registry URL"
  type        = "String"
  value       = var.ecr_registry

  tags = local.common_tags
}

resource "aws_ssm_parameter" "ecr_repository" {
  name        = "${local.ps_prefix}/ecr-repository"
  description = "ECR repository name"
  type        = "String"
  value       = var.ecr_repository_name

  tags = local.common_tags
}

resource "aws_ssm_parameter" "domain_name" {
  name        = "${local.ps_prefix}/domain-name"
  description = "Portal domain name"
  type        = "String"
  value       = var.domain_name

  tags = local.common_tags
}

resource "aws_ssm_parameter" "s3_bucket" {
  name        = "${local.ps_prefix}/s3-bucket"
  description = "S3 bucket for user storage"
  type        = "String"
  value       = var.s3_bucket_name

  tags = local.common_tags
}

resource "aws_ssm_parameter" "db_secret_arn" {
  name        = "${local.ps_prefix}/db-secret-arn"
  description = "Database credentials secret ARN"
  type        = "String"
  value       = var.db_secret_arn

  tags = local.common_tags
}

resource "aws_ssm_parameter" "app_secret_arn" {
  name        = "${local.ps_prefix}/app-secret-arn"
  description = "Application secret ARN"
  type        = "String"
  value       = var.app_secret_arn

  tags = local.common_tags
}

resource "aws_ssm_parameter" "cognito_secret_arn" {
  name        = "${local.ps_prefix}/cognito-secret-arn"
  description = "Cognito secret ARN"
  type        = "String"
  value       = var.cognito_secret_arn

  tags = local.common_tags
}

resource "aws_ssm_parameter" "guacamole_secret_arn" {
  name        = "${local.ps_prefix}/guacamole-secret-arn"
  description = "Guacamole JSON auth secret ARN for RDP integration"
  type        = "String"
  value       = var.guacamole_secret_arn

  tags = local.common_tags
}

resource "aws_ssm_parameter" "dc_domain_password_secret_arn" {
  name        = "${local.ps_prefix}/dc-domain-password-secret-arn"
  description = "ARN of the Secrets Manager secret holding the prebaked DC Administrator password (resolved at portal startup)"
  type        = "String"
  value       = var.dc_domain_password_secret_arn

  tags = local.common_tags
}

resource "aws_ssm_parameter" "guacamole_base_url" {
  name        = "${local.ps_prefix}/guacamole-base-url"
  description = "Guacamole public URL for browser (e.g., https://domain.com/guacamole)"
  type        = "String"
  value       = var.guacamole_base_url

  tags = local.common_tags
}

resource "aws_ssm_parameter" "guacamole_api_base_url" {
  name        = "${local.ps_prefix}/guacamole-api-base-url"
  description = "Guacamole internal URL for API calls (e.g., http://guacamole-client.internal:8080/guacamole)"
  type        = "String"
  value       = var.guacamole_api_base_url

  tags = local.common_tags
}

# Engine SSM parameters
resource "aws_ssm_parameter" "engine_ecs_cluster_arn" {
  name        = "${local.ps_prefix}/engine-ecs-cluster-arn"
  description = "ECS cluster ARN for engine provisioner"
  type        = "String"
  value       = var.engine_ecs_cluster_arn

  tags = local.common_tags
}

resource "aws_ssm_parameter" "engine_task_definition_arn" {
  name        = "${local.ps_prefix}/engine-task-definition-arn"
  description = "ECS task definition family for engine provisioner"
  type        = "String"
  value       = var.engine_task_definition_family

  tags = local.common_tags
}

resource "aws_ssm_parameter" "engine_ecs_security_group_id" {
  name        = "${local.ps_prefix}/engine-ecs-security-group-id"
  description = "Security group ID for engine ECS tasks"
  type        = "String"
  value       = var.engine_ecs_security_group_id

  tags = local.common_tags
}

resource "aws_ssm_parameter" "engine_private_subnet_ids" {
  name        = "${local.ps_prefix}/engine-private-subnet-ids"
  description = "Private subnet IDs for engine ECS tasks"
  type        = "String"
  value       = var.engine_private_subnet_ids

  tags = local.common_tags
}

resource "aws_ssm_parameter" "sqs_cms_url" {
  name        = "${local.ps_prefix}/sqs-cms-url"
  description = "SQS queue URL for CMS worker"
  type        = "String"
  value       = var.sqs_cms_url

  tags = local.common_tags
}

resource "aws_ssm_parameter" "sqs_engine_url" {
  name        = "${local.ps_prefix}/sqs-engine-url"
  description = "SQS queue URL for Engine worker"
  type        = "String"
  value       = var.sqs_engine_url

  tags = local.common_tags
}

resource "aws_ssm_parameter" "sqs_mc_url" {
  name        = "${local.ps_prefix}/sqs-mc-url"
  description = "SQS queue URL for Mission Control worker"
  type        = "String"
  value       = var.sqs_mc_url

  tags = local.common_tags
}

resource "aws_ssm_parameter" "redis_endpoint" {
  count = var.enable_redis ? 1 : 0

  name        = "${local.ps_prefix}/redis-endpoint"
  description = "Redis endpoint for Django Channels"
  type        = "String"
  value       = var.redis_endpoint

  tags = local.common_tags
}

# Explicit channel-layer backend posture (ADR-018, #849). Always written with a
# non-empty value so the runtime is unambiguous and independent of whether the
# redis-endpoint write succeeded: a "redis" posture without a reachable endpoint
# makes Django fail closed at startup instead of silently using in-memory.
# Decoupled from enable_autoscaling — this is wiring posture, not compute topology.
resource "aws_ssm_parameter" "channel_layer_backend" {
  name        = "${local.ps_prefix}/channel-layer-backend"
  description = "Django Channels backend posture (redis | in_memory)"
  type        = "String"
  value       = var.enable_redis ? "redis" : "in_memory"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "db_host_override" {
  count = var.enable_db_host_override ? 1 : 0

  name        = "${local.ps_prefix}/db-host-override"
  description = "Database host override"
  type        = "String"
  value       = var.db_host_override

  tags = local.common_tags
}

resource "aws_ssm_parameter" "email_backend" {
  name        = "${local.ps_prefix}/email-backend"
  description = "Django email backend class"
  type        = "String"
  value       = var.email_backend

  tags = local.common_tags
}

resource "aws_ssm_parameter" "ctf_from_email" {
  name        = "${local.ps_prefix}/ctf-from-email"
  description = "From address for CTF emails"
  type        = "String"
  value       = var.ctf_from_email

  tags = local.common_tags
}

resource "aws_ssm_parameter" "ctfd_platform_url" {
  count = var.ctfd_platform_url != "" ? 1 : 0

  name        = "${local.ps_prefix}/ctfd-platform-url"
  description = "Public URL for the standalone CTFd platform"
  type        = "String"
  value       = var.ctfd_platform_url

  tags = local.common_tags
}
