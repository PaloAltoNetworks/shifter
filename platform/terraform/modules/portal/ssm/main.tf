# SSM Module - Portal Deployment
#
# Creates:
# - Parameter Store parameters for deployment configuration
# - SSM document for portal container deployment
#
# The SSM document reads config from Parameter Store and can be invoked by:
# - CI/CD pipeline (direct SSM send-command)
# - ASG lifecycle hook (via EventBridge)

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

# ------------------------------------------------------------------------------
# SSM Document - Portal Deployment
# ------------------------------------------------------------------------------

resource "aws_ssm_document" "portal_deploy" {
  name            = "${var.name_prefix}-portal-deploy"
  document_type   = "Command"
  document_format = "JSON"

  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Deploy Shifter Portal containers. Reads config from Parameter Store."
    parameters = {
      LifecycleHookName = {
        type        = "String"
        description = "ASG lifecycle hook name (empty for CI/CD triggered deploys)"
        default     = ""
      }
      AutoScalingGroupName = {
        type        = "String"
        description = "ASG name (empty for single instance mode)"
        default     = ""
      }
      LifecycleActionToken = {
        type        = "String"
        description = "Lifecycle action token (empty for CI/CD triggered deploys)"
        default     = ""
      }
    }
    mainSteps = [
      {
        action = "aws:runShellScript"
        name   = "deployPortalContainers"
        inputs = {
          timeoutSeconds = 600
          runCommand = [
            "#!/bin/bash",
            "set -euo pipefail",
            "",
            "# ------------------------------------------------------------------------------",
            "# Configuration",
            "# ------------------------------------------------------------------------------",
            "PS_PREFIX='${local.ps_prefix}'",
            "AWS_REGION='${var.aws_region}'",
            "LIFECYCLE_HOOK_NAME='{{LifecycleHookName}}'",
            "ASG_NAME='{{AutoScalingGroupName}}'",
            "LIFECYCLE_ACTION_TOKEN='{{LifecycleActionToken}}'",
            "",
            "# Get instance ID from metadata",
            "TOKEN=$(curl -s -X PUT \"http://169.254.169.254/latest/api/token\" -H \"X-aws-ec2-metadata-token-ttl-seconds: 21600\")",
            "INSTANCE_ID=$(curl -s -H \"X-aws-ec2-metadata-token: $TOKEN\" http://169.254.169.254/latest/meta-data/instance-id)",
            "",
            "echo \"Starting portal deployment on instance $INSTANCE_ID\"",
            "",
            "# Function to complete lifecycle action",
            "complete_lifecycle_action() {",
            "  local result=$1",
            "  if [ -n \"$LIFECYCLE_HOOK_NAME\" ] && [ -n \"$ASG_NAME\" ]; then",
            "    echo \"Completing lifecycle action with result: $result\"",
            "    if [ -n \"$LIFECYCLE_ACTION_TOKEN\" ]; then",
            "      aws autoscaling complete-lifecycle-action \\",
            "        --lifecycle-hook-name \"$LIFECYCLE_HOOK_NAME\" \\",
            "        --auto-scaling-group-name \"$ASG_NAME\" \\",
            "        --lifecycle-action-token \"$LIFECYCLE_ACTION_TOKEN\" \\",
            "        --lifecycle-action-result \"$result\" \\",
            "        --region \"$AWS_REGION\"",
            "    else",
            "      aws autoscaling complete-lifecycle-action \\",
            "        --lifecycle-hook-name \"$LIFECYCLE_HOOK_NAME\" \\",
            "        --auto-scaling-group-name \"$ASG_NAME\" \\",
            "        --instance-id \"$INSTANCE_ID\" \\",
            "        --lifecycle-action-result \"$result\" \\",
            "        --region \"$AWS_REGION\"",
            "    fi",
            "  fi",
            "}",
            "",
            "# Trap errors and abandon lifecycle on failure",
            "trap 'echo \"Deployment failed!\"; complete_lifecycle_action ABANDON; exit 1' ERR",
            "",
            "# ------------------------------------------------------------------------------",
            "# Read configuration from Parameter Store",
            "# ------------------------------------------------------------------------------",
            "echo \"Reading configuration from Parameter Store...\"",
            "",
            "get_param() {",
            "  aws ssm get-parameter --name \"$1\" --query 'Parameter.Value' --output text --region \"$AWS_REGION\"",
            "}",
            "",
            "IMAGE_TAG=$(get_param \"$PS_PREFIX/image-tag\")",
            "ECR_REGISTRY=$(get_param \"$PS_PREFIX/ecr-registry\")",
            "ECR_REPOSITORY=$(get_param \"$PS_PREFIX/ecr-repository\")",
            "DOMAIN_NAME=$(get_param \"$PS_PREFIX/domain-name\")",
            "S3_BUCKET=$(get_param \"$PS_PREFIX/s3-bucket\")",
            "DB_SECRET_ARN=$(get_param \"$PS_PREFIX/db-secret-arn\")",
            "APP_SECRET_ARN=$(get_param \"$PS_PREFIX/app-secret-arn\")",
            "COGNITO_SECRET_ARN=$(get_param \"$PS_PREFIX/cognito-secret-arn\")",
            "PULUMI_ECS_CLUSTER_ARN=$(get_param \"$PS_PREFIX/pulumi-ecs-cluster-arn\")",
            "PULUMI_TASK_DEFINITION_ARN=$(get_param \"$PS_PREFIX/pulumi-task-definition-arn\")",
            "PULUMI_ECS_SECURITY_GROUP_ID=$(get_param \"$PS_PREFIX/pulumi-ecs-security-group-id\")",
            "PULUMI_PRIVATE_SUBNET_IDS=$(get_param \"$PS_PREFIX/pulumi-private-subnet-ids\")",
            "SQS_CMS_URL=$(get_param \"$PS_PREFIX/sqs-cms-url\")",
            "SQS_ENGINE_URL=$(get_param \"$PS_PREFIX/sqs-engine-url\")",
            "SQS_MC_URL=$(get_param \"$PS_PREFIX/sqs-mc-url\")",
            "REDIS_ENDPOINT=$(get_param \"$PS_PREFIX/redis-endpoint\")",
            "",
            "IMAGE=\"$ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG\"",
            "echo \"Deploying image: $IMAGE\"",
            "",
            "# ------------------------------------------------------------------------------",
            "# Build container environment variables",
            "# ------------------------------------------------------------------------------",
            "COMMON_ENV=\"-e AWS_REGION=$AWS_REGION\"",
            "COMMON_ENV=\"$COMMON_ENV -e AWS_S3_BUCKET_NAME=$S3_BUCKET\"",
            "COMMON_ENV=\"$COMMON_ENV -e DB_SECRET_ARN=$DB_SECRET_ARN\"",
            "COMMON_ENV=\"$COMMON_ENV -e APP_SECRET_ARN=$APP_SECRET_ARN\"",
            "COMMON_ENV=\"$COMMON_ENV -e COGNITO_SECRET_ARN=$COGNITO_SECRET_ARN\"",
            "COMMON_ENV=\"$COMMON_ENV -e DJANGO_ALLOWED_HOSTS=$DOMAIN_NAME\"",
            "COMMON_ENV=\"$COMMON_ENV -e DJANGO_CSRF_TRUSTED_ORIGINS=https://$DOMAIN_NAME\"",
            "COMMON_ENV=\"$COMMON_ENV -e SITE_URL=https://$DOMAIN_NAME\"",
            "COMMON_ENV=\"$COMMON_ENV -e PULUMI_ECS_CLUSTER_ARN=$PULUMI_ECS_CLUSTER_ARN\"",
            "COMMON_ENV=\"$COMMON_ENV -e PULUMI_TASK_DEFINITION_ARN=$PULUMI_TASK_DEFINITION_ARN\"",
            "COMMON_ENV=\"$COMMON_ENV -e PULUMI_ECS_SECURITY_GROUP_ID=$PULUMI_ECS_SECURITY_GROUP_ID\"",
            "COMMON_ENV=\"$COMMON_ENV -e PULUMI_PRIVATE_SUBNET_IDS=$PULUMI_PRIVATE_SUBNET_IDS\"",
            "COMMON_ENV=\"$COMMON_ENV -e SQS_CMS_URL=$SQS_CMS_URL\"",
            "COMMON_ENV=\"$COMMON_ENV -e SQS_ENGINE_URL=$SQS_ENGINE_URL\"",
            "COMMON_ENV=\"$COMMON_ENV -e SQS_MC_URL=$SQS_MC_URL\"",
            "",
            "# Add Redis if configured",
            "if [ -n \"$REDIS_ENDPOINT\" ]; then",
            "  COMMON_ENV=\"$COMMON_ENV -e REDIS_HOST=$REDIS_ENDPOINT\"",
            "fi",
            "",
            "# ------------------------------------------------------------------------------",
            "# Deploy containers",
            "# ------------------------------------------------------------------------------",
            "echo \"Pulling image...\"",
            "docker pull \"$IMAGE\"",
            "",
            "echo \"Stopping existing containers...\"",
            "docker stop portal worker-cms worker-engine worker-mc 2>/dev/null || true",
            "docker rm portal worker-cms worker-engine worker-mc 2>/dev/null || true",
            "",
            "echo \"Starting portal...\"",
            "eval docker run -d --name portal --restart unless-stopped -p 8000:8000 $COMMON_ENV \"$IMAGE\"",
            "",
            "echo \"Starting workers...\"",
            "eval docker run -d --name worker-cms --restart unless-stopped $COMMON_ENV \"$IMAGE\" python manage.py run_worker --queue cms",
            "eval docker run -d --name worker-engine --restart unless-stopped $COMMON_ENV \"$IMAGE\" python manage.py run_worker --queue engine",
            "eval docker run -d --name worker-mc --restart unless-stopped $COMMON_ENV \"$IMAGE\" python manage.py run_worker --queue mc",
            "",
            "echo \"All containers started\"",
            "docker ps",
            "",
            "# ------------------------------------------------------------------------------",
            "# Complete lifecycle action on success",
            "# ------------------------------------------------------------------------------",
            "complete_lifecycle_action CONTINUE",
            "",
            "echo \"Portal deployment complete!\""
          ]
        }
      }
    ]
  })

  tags = local.common_tags
}
