# SSM Module Variables
#
# Parameters for SSM documents and Parameter Store configuration
# used for portal deployment via lifecycle hooks and CI/CD.

variable "environment" {
  description = "Environment name (dev, prod)"
  type        = string
}

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
}

# ------------------------------------------------------------------------------
# ECR Configuration
# ------------------------------------------------------------------------------

variable "ecr_registry" {
  description = "ECR registry URL (e.g., 123456789.dkr.ecr.us-east-2.amazonaws.com)"
  type        = string
}

variable "ecr_repository_name" {
  description = "ECR repository name (e.g., shifter-dev-portal)"
  type        = string
}

variable "initial_image_tag" {
  description = "Initial image tag to deploy (updated by CI/CD)"
  type        = string
  default     = "latest"
}

# ------------------------------------------------------------------------------
# Secrets Manager ARNs
# ------------------------------------------------------------------------------

variable "db_secret_arn" {
  description = "ARN of database credentials secret"
  type        = string
}

variable "app_secret_arn" {
  description = "ARN of application secret"
  type        = string
}

variable "cognito_secret_arn" {
  description = "ARN of Cognito secret"
  type        = string
}

# ------------------------------------------------------------------------------
# Application Configuration
# ------------------------------------------------------------------------------

variable "domain_name" {
  description = "Portal domain name for Django settings"
  type        = string
}

variable "s3_bucket_name" {
  description = "S3 bucket name for user storage"
  type        = string
}

# ------------------------------------------------------------------------------
# Pulumi Provisioner Configuration
# ------------------------------------------------------------------------------

variable "pulumi_ecs_cluster_arn" {
  description = "ARN of ECS cluster for Pulumi provisioner"
  type        = string
}

variable "pulumi_task_definition_arn" {
  description = "ARN of ECS task definition for Pulumi provisioner"
  type        = string
}

variable "pulumi_ecs_security_group_id" {
  description = "Security group ID for Pulumi ECS tasks"
  type        = string
}

variable "pulumi_private_subnet_ids" {
  description = "Comma-separated list of private subnet IDs for Pulumi ECS"
  type        = string
}

# ------------------------------------------------------------------------------
# Messaging Configuration
# ------------------------------------------------------------------------------

variable "sqs_cms_url" {
  description = "SQS queue URL for CMS worker"
  type        = string
}

variable "sqs_engine_url" {
  description = "SQS queue URL for Engine worker"
  type        = string
}

variable "sqs_mc_url" {
  description = "SQS queue URL for Mission Control worker"
  type        = string
}

variable "redis_endpoint" {
  description = "Redis endpoint for Django Channels (empty string if not using Redis)"
  type        = string
  default     = ""
}

# ------------------------------------------------------------------------------
# ASG Lifecycle Hook Configuration
# ------------------------------------------------------------------------------

variable "lifecycle_hook_name" {
  description = "Name of the ASG lifecycle hook (empty if not using lifecycle hooks)"
  type        = string
  default     = ""
}

variable "asg_name" {
  description = "Name of the Auto Scaling Group (empty if single instance mode)"
  type        = string
  default     = ""
}
