# ------------------------------------------------------------------------------
# Core Variables
# ------------------------------------------------------------------------------

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, prod)"
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
}

# ------------------------------------------------------------------------------
# Networking
# ------------------------------------------------------------------------------

variable "vpc_id" {
  description = "ID of the VPC where Guacamole will be deployed"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for ECS tasks and RDS"
  type        = list(string)
}

variable "range_vpc_cidr" {
  description = "CIDR block of the Range VPC (for guacd egress rules)"
  type        = string
}

variable "portal_security_group_id" {
  description = "Security group ID of the Portal EC2 instance (for direct API access to guacamole-client)"
  type        = string
  default     = ""
}

variable "enable_portal_sg_rule" {
  description = "Whether to create the portal-to-guacamole security group rule. Use this instead of testing portal_security_group_id to avoid count depending on unknown values."
  type        = bool
  default     = false
}

# ------------------------------------------------------------------------------
# Shared ALB (Portal ALB)
# ------------------------------------------------------------------------------

variable "alb_listener_arn" {
  description = "ARN of the Portal ALB HTTPS listener"
  type        = string
}

variable "alb_security_group_id" {
  description = "Security group ID of the Portal ALB"
  type        = string
}

# ------------------------------------------------------------------------------
# ECR Configuration
# ------------------------------------------------------------------------------

variable "guacd_ecr_repository_url" {
  description = "URL of the ECR repository for the guacd image"
  type        = string
}

variable "guacd_ecr_repository_arn" {
  description = "ARN of the guacd ECR repository (for IAM scoping)"
  type        = string
}

variable "guacamole_client_ecr_repository_url" {
  description = "URL of the ECR repository for the guacamole-client image"
  type        = string
}

variable "guacamole_client_ecr_repository_arn" {
  description = "ARN of the guacamole-client ECR repository (for IAM scoping)"
  type        = string
}

variable "guacd_image_tag" {
  description = "Docker image tag for guacd"
  type        = string
}

variable "guacamole_client_image_tag" {
  description = "Docker image tag for guacamole-client"
  type        = string
}

# ------------------------------------------------------------------------------
# ECS Configuration
# ------------------------------------------------------------------------------

variable "guacd_cpu" {
  description = "CPU units for the guacd task (1024 = 1 vCPU)"
  type        = number
}

variable "guacd_memory" {
  description = "Memory in MB for the guacd task"
  type        = number
}

variable "guacamole_client_cpu" {
  description = "CPU units for the guacamole-client task (1024 = 1 vCPU)"
  type        = number
}

variable "guacamole_client_memory" {
  description = "Memory in MB for the guacamole-client task"
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

# ------------------------------------------------------------------------------
# Database Configuration
# ------------------------------------------------------------------------------

variable "db_instance_class" {
  description = "RDS instance class for Guacamole database"
  type        = string
}

variable "db_allocated_storage" {
  description = "Allocated storage for RDS in GB"
  type        = number
}

variable "db_max_allocated_storage" {
  description = "Maximum allocated storage for RDS autoscaling in GB"
  type        = number
}

variable "db_engine_version" {
  description = "PostgreSQL engine version"
  type        = string
}

variable "db_multi_az" {
  description = "Enable Multi-AZ deployment for RDS"
  type        = bool
}

variable "db_backup_retention_days" {
  description = "Number of days to retain automated backups"
  type        = number
}

variable "db_deletion_protection" {
  description = "Enable deletion protection for RDS"
  type        = bool
}

variable "db_skip_final_snapshot" {
  description = "Skip final snapshot when deleting RDS"
  type        = bool
}

# ------------------------------------------------------------------------------
# Auto Scaling
# ------------------------------------------------------------------------------

variable "enable_autoscaling" {
  description = "Enable auto scaling for ECS services"
  type        = bool
}

variable "autoscaling_min_capacity" {
  description = "Minimum number of tasks for auto scaling"
  type        = number
}

variable "autoscaling_max_capacity" {
  description = "Maximum number of tasks for auto scaling"
  type        = number
}

variable "autoscaling_cpu_target" {
  description = "Target CPU utilization percentage for auto scaling"
  type        = number
}

# ------------------------------------------------------------------------------
# Secrets
# ------------------------------------------------------------------------------

variable "secrets_recovery_window_days" {
  description = "Recovery window in days for Secrets Manager (0 for immediate deletion)"
  type        = number
}

# ------------------------------------------------------------------------------
# OIDC/Cognito Authentication
# ------------------------------------------------------------------------------

variable "enable_oidc" {
  description = "Enable OpenID Connect authentication via Cognito"
  type        = bool
}

variable "cognito_user_pool_id" {
  description = "Cognito user pool ID (required when enable_oidc = true)"
  type        = string
  default     = ""
}

variable "cognito_domain" {
  description = "Cognito hosted UI domain (full URL, e.g., https://xxx.auth.us-east-2.amazoncognito.com)"
  type        = string
  default     = ""
}

variable "aws_region" {
  description = "AWS region (required for constructing Cognito endpoints)"
  type        = string
  default     = "us-east-2"
}

variable "domain_name" {
  description = "Portal domain name (for constructing Guacamole redirect URI)"
  type        = string
  default     = ""
}
