# OpenBAS Module Variables

# ------------------------------------------------------------------------------
# Required Variables
# ------------------------------------------------------------------------------

variable "name_prefix" {
  description = "Prefix for resource names (e.g., dev-range)"
  type        = string
}

variable "vpc_id" {
  description = "ID of the Range VPC"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block of the Range VPC (e.g., 10.1.0.0/16)"
  type        = string
}

variable "portal_vpc_cidr" {
  description = "CIDR block of the Portal VPC (for API access)"
  type        = string
}

variable "private_route_table_id" {
  description = "ID of the private route table for subnet associations"
  type        = string
}

variable "base_url" {
  description = "Base URL for OpenBAS (e.g., https://portal.example.com/shifter-mirage/bas)"
  type        = string
}

variable "openbas_image" {
  description = "Docker image for OpenBAS (e.g., openbas/openbas:latest)"
  type        = string
}

variable "tags" {
  description = "Common tags to apply to all resources"
  type        = map(string)
}

# ------------------------------------------------------------------------------
# ECS Configuration
# ------------------------------------------------------------------------------

variable "task_cpu" {
  description = "CPU units for ECS task (1024 = 1 vCPU)"
  type        = number
  default     = 1024
}

variable "task_memory" {
  description = "Memory for ECS task in MB"
  type        = number
  default     = 4096
}

variable "desired_count" {
  description = "Desired number of ECS tasks"
  type        = number
  default     = 2
}

variable "enable_autoscaling" {
  description = "Enable auto scaling for ECS service"
  type        = bool
  default     = true
}

variable "min_capacity" {
  description = "Minimum number of ECS tasks (when autoscaling enabled)"
  type        = number
  default     = 2
}

variable "max_capacity" {
  description = "Maximum number of ECS tasks (when autoscaling enabled)"
  type        = number
  default     = 4
}

# ------------------------------------------------------------------------------
# Database Configuration
# ------------------------------------------------------------------------------

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.small"
}

variable "db_engine_version" {
  description = "PostgreSQL engine version"
  type        = string
  default     = "15.4"
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "openbas"
}

variable "db_username" {
  description = "Database master username"
  type        = string
  default     = "openbas"
}

variable "db_allocated_storage" {
  description = "Initial allocated storage in GB"
  type        = number
  default     = 20
}

variable "db_max_allocated_storage" {
  description = "Maximum storage for autoscaling in GB"
  type        = number
  default     = 100
}

variable "db_multi_az" {
  description = "Enable Multi-AZ deployment for RDS"
  type        = bool
  default     = true
}

variable "db_backup_retention_days" {
  description = "Number of days to retain automated backups"
  type        = number
  default     = 7
}

variable "db_deletion_protection" {
  description = "Enable deletion protection for RDS"
  type        = bool
  default     = false
}

variable "db_skip_final_snapshot" {
  description = "Skip final snapshot when destroying RDS"
  type        = bool
  default     = true
}

variable "enable_db_log_exports" {
  description = "Enable CloudWatch log exports for RDS"
  type        = bool
  default     = true
}

# ------------------------------------------------------------------------------
# Logging Configuration
# ------------------------------------------------------------------------------

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}
