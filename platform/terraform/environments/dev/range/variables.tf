# Environment variables - NO DEFAULTS

variable "environment" {
  description = "Environment name (e.g., prod, dev)"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the Range VPC (e.g., 10.1.0.0/16)"
  type        = string
}

variable "portal_vpc_cidr" {
  description = "CIDR block for the Portal VPC (for SSH access from browser terminal)"
  type        = string
}

variable "tags" {
  description = "Common tags to apply to all resources"
  type        = map(string)
}

# ------------------------------------------------------------------------------
# Phase 5: Additional Log Sources
# ------------------------------------------------------------------------------

variable "enable_flow_logs" {
  description = "Enable VPC flow logs"
  type        = bool
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

# ------------------------------------------------------------------------------
# Range Instance IAM
# ------------------------------------------------------------------------------

variable "agent_s3_bucket" {
  description = "S3 bucket name for agent installers (for range instance S3 read access)"
  type        = string
}

# ------------------------------------------------------------------------------
# VM-Series NGFW Configuration
# ------------------------------------------------------------------------------

variable "vm_series_ami_id" {
  description = "VM-Series AMI ID. Empty string disables NGFW provisioning."
  type        = string
  default     = ""
}

variable "vm_series_instance_type" {
  description = "EC2 instance type for VM-Series NGFW"
  type        = string
  default     = "m5.xlarge"
}

# ------------------------------------------------------------------------------
# Persistent NGFW Infrastructure
# ------------------------------------------------------------------------------

variable "enable_ngfw_infrastructure" {
  description = "Enable persistent NGFW infrastructure (subnet, security groups, IAM role)"
  type        = bool
}

# ------------------------------------------------------------------------------
# OpenBAS Configuration
# ------------------------------------------------------------------------------

variable "enable_openbas" {
  description = "Enable OpenBAS shared infrastructure"
  type        = bool
  default     = false
}

variable "openbas_base_url" {
  description = "Base URL for OpenBAS (e.g., https://portal.example.com/shifter-mirage/bas)"
  type        = string
  default     = ""
}

variable "openbas_image" {
  description = "Docker image for OpenBAS"
  type        = string
  default     = "openbas/openbas:latest"
}

variable "openbas_task_cpu" {
  description = "CPU units for OpenBAS ECS task (1024 = 1 vCPU)"
  type        = number
  default     = 1024
}

variable "openbas_task_memory" {
  description = "Memory for OpenBAS ECS task in MB"
  type        = number
  default     = 4096
}

variable "openbas_desired_count" {
  description = "Desired number of OpenBAS ECS tasks"
  type        = number
  default     = 2
}

variable "openbas_enable_autoscaling" {
  description = "Enable auto scaling for OpenBAS ECS service"
  type        = bool
  default     = true
}

variable "openbas_min_capacity" {
  description = "Minimum number of OpenBAS ECS tasks"
  type        = number
  default     = 2
}

variable "openbas_max_capacity" {
  description = "Maximum number of OpenBAS ECS tasks"
  type        = number
  default     = 4
}

variable "openbas_db_instance_class" {
  description = "RDS instance class for OpenBAS database"
  type        = string
  default     = "db.t3.small"
}

variable "openbas_db_multi_az" {
  description = "Enable Multi-AZ deployment for OpenBAS RDS"
  type        = bool
  default     = true
}

variable "openbas_db_backup_retention_days" {
  description = "Backup retention days for OpenBAS RDS"
  type        = number
  default     = 7
}

variable "openbas_db_deletion_protection" {
  description = "Enable deletion protection for OpenBAS RDS"
  type        = bool
  default     = false
}

variable "openbas_db_skip_final_snapshot" {
  description = "Skip final snapshot when destroying OpenBAS RDS"
  type        = bool
  default     = true
}
