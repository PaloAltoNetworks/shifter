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

variable "alb_security_group_id" {
  description = "Security group ID of the ALB (for ingress rule)"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
}

variable "ecr_repository_arn" {
  description = "ARN of the ECR repository"
  type        = string
}

variable "ecr_repository_url" {
  description = "URL of the ECR repository"
  type        = string
}

variable "db_secret_arn" {
  description = "ARN of the Secrets Manager secret for RDS credentials"
  type        = string
}

variable "app_port" {
  description = "Port the Django app listens on"
  type        = number
}

variable "root_volume_size" {
  description = "Size of root EBS volume in GB"
  type        = number
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
}
