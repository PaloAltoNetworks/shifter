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
