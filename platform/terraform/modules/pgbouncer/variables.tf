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
  default     = {}
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

# ------------------------------------------------------------------------------
# Networking
# ------------------------------------------------------------------------------

variable "vpc_id" {
  description = "ID of the VPC where PgBouncer will be deployed"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for ECS tasks"
  type        = list(string)
}

variable "portal_security_group_id" {
  description = "Security group ID of the Portal EC2 instance"
  type        = string
}

variable "additional_client_security_group_ids" {
  description = "Additional security group IDs that need access to PgBouncer (e.g., Pulumi provisioner)"
  type        = list(string)
  default     = []
}

# ------------------------------------------------------------------------------
# Database Configuration
# ------------------------------------------------------------------------------

variable "rds_endpoint" {
  description = "RDS endpoint (hostname:port)"
  type        = string
}

variable "rds_security_group_id" {
  description = "Security group ID of the RDS instance"
  type        = string
}

variable "db_credentials_secret_arn" {
  description = "ARN of the Secrets Manager secret containing DB credentials"
  type        = string
}

variable "db_name" {
  description = "Name of the database"
  type        = string
  default     = "shifter"
}

# ------------------------------------------------------------------------------
# ECS Configuration
# ------------------------------------------------------------------------------

variable "cpu" {
  description = "CPU units for the PgBouncer task (1024 = 1 vCPU)"
  type        = number
  default     = 256 # 0.25 vCPU
}

variable "memory" {
  description = "Memory in MB for the PgBouncer task"
  type        = number
  default     = 512
}

variable "desired_count" {
  description = "Desired number of PgBouncer tasks"
  type        = number
  default     = 2
}

# ------------------------------------------------------------------------------
# PgBouncer Configuration
# ------------------------------------------------------------------------------

variable "pool_mode" {
  description = "PgBouncer pool mode (transaction, session, statement)"
  type        = string
  default     = "transaction"
}

variable "max_client_conn" {
  description = "Maximum number of client connections per task"
  type        = number
  default     = 1000
}

variable "default_pool_size" {
  description = "Default pool size per user/database pair"
  type        = number
  default     = 20
}

variable "min_pool_size" {
  description = "Minimum pool size"
  type        = number
  default     = 5
}

variable "reserve_pool_size" {
  description = "Reserve pool size for emergency connections"
  type        = number
  default     = 5
}

variable "pgbouncer_image" {
  description = "PgBouncer Docker image"
  type        = string
  default     = "bitnami/pgbouncer:latest"
}

# ------------------------------------------------------------------------------
# Auth Query Configuration (for SCRAM-SHA-256 support)
# ------------------------------------------------------------------------------

variable "auth_user_secret_arn" {
  description = "ARN of Secrets Manager secret containing pgbouncer auth user credentials (username/password)"
  type        = string
}
