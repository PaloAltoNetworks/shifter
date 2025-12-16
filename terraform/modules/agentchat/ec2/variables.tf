variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "subnet_id" {
  description = "Subnet ID for EC2 instance (private subnet)"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
}

variable "root_volume_size" {
  description = "Size of root EBS volume in GB"
  type        = number
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
}

variable "openwebui_db_secret_arn" {
  description = "ARN of the Secrets Manager secret containing OpenWebUI DB credentials"
  type        = string
  default     = ""
}

variable "db_resource_id" {
  description = "Resource ID of the RDS instance (for IAM DB authentication)"
  type        = string
  default     = ""
}

variable "environment" {
  description = "Environment name (dev, prod) - used for SSH key secret pattern"
  type        = string
}

variable "mcp_shifter_ecr_arn" {
  description = "ARN of the mcp-shifter ECR repository"
  type        = string
  default     = ""
}
