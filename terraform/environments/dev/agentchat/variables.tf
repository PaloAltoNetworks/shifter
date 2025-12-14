# Environment variables - NO DEFAULTS

# ------------------------------------------------------------------------------
# General
# ------------------------------------------------------------------------------

variable "environment" {
  description = "Environment name (e.g., prod, dev)"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "tags" {
  description = "Common tags to apply to all resources"
  type        = map(string)
}

# ------------------------------------------------------------------------------
# EC2
# ------------------------------------------------------------------------------

variable "ec2_instance_type" {
  description = "EC2 instance type for AgentChat"
  type        = string
}

variable "ec2_root_volume_size" {
  description = "Size of EC2 root volume in GB"
  type        = number
}

# ------------------------------------------------------------------------------
# Bedrock
# ------------------------------------------------------------------------------

variable "bedrock_region" {
  description = "AWS region for Bedrock API calls (may differ from infra region)"
  type        = string
}
