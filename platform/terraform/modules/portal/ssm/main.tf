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
  count = var.guacamole_secret_arn != "" ? 1 : 0

  name        = "${local.ps_prefix}/guacamole-secret-arn"
  description = "Guacamole JSON auth secret ARN for RDP integration"
  type        = "String"
  value       = var.guacamole_secret_arn

  tags = local.common_tags
}

resource "aws_ssm_parameter" "guacamole_base_url" {
  count = var.guacamole_base_url != "" ? 1 : 0

  name        = "${local.ps_prefix}/guacamole-base-url"
  description = "Guacamole public URL for browser (e.g., https://domain.com/guacamole)"
  type        = "String"
  value       = var.guacamole_base_url

  tags = local.common_tags
}

resource "aws_ssm_parameter" "guacamole_api_base_url" {
  count = var.guacamole_api_base_url != "" ? 1 : 0

  name        = "${local.ps_prefix}/guacamole-api-base-url"
  description = "Guacamole internal URL for API calls (e.g., http://guacamole-client.internal:8080/guacamole)"
  type        = "String"
  value       = var.guacamole_api_base_url

  tags = local.common_tags
}

resource "aws_ssm_parameter" "pulumi_ecs_cluster_arn" {
  name        = "${local.ps_prefix}/pulumi-ecs-cluster-arn"
  description = "ECS cluster ARN for Pulumi provisioner"
  type        = "String"
  value       = var.pulumi_ecs_cluster_arn

  tags = local.common_tags
}

resource "aws_ssm_parameter" "pulumi_task_definition_arn" {
  name        = "${local.ps_prefix}/pulumi-task-definition-arn"
  description = "ECS task definition ARN for Pulumi provisioner"
  type        = "String"
  value       = var.pulumi_task_definition_arn

  tags = local.common_tags
}

resource "aws_ssm_parameter" "pulumi_ecs_security_group_id" {
  name        = "${local.ps_prefix}/pulumi-ecs-security-group-id"
  description = "Security group ID for Pulumi ECS tasks"
  type        = "String"
  value       = var.pulumi_ecs_security_group_id

  tags = local.common_tags
}

resource "aws_ssm_parameter" "pulumi_private_subnet_ids" {
  name        = "${local.ps_prefix}/pulumi-private-subnet-ids"
  description = "Private subnet IDs for Pulumi ECS tasks"
  type        = "String"
  value       = var.pulumi_private_subnet_ids

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
  name        = "${local.ps_prefix}/redis-endpoint"
  description = "Redis endpoint for Django Channels"
  type        = "String"
  value       = var.redis_endpoint

  tags = local.common_tags
}
