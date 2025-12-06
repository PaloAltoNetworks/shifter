# Environment variables - NO DEFAULTS
# All values provided via terraform.tfvars (synced to GitHub secrets)

variable "environment" {
  description = "Environment name (e.g., prod, dev)"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
}

variable "az_count" {
  description = "Number of availability zones to use"
  type        = number
}

variable "enable_nat_gateway" {
  description = "Whether to create a NAT gateway for private subnet internet access"
  type        = bool
}

variable "tags" {
  description = "Common tags to apply to all resources"
  type        = map(string)
}
