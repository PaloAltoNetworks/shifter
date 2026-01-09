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

# ------------------------------------------------------------------------------
# ECR Configuration
# ------------------------------------------------------------------------------

variable "guacd_ecr_repository_url" {
  description = "URL of the ECR repository for the guacd image"
  type        = string
}

variable "guacamole_client_ecr_repository_url" {
  description = "URL of the ECR repository for the guacamole-client image"
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
