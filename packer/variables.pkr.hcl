// All variables are required - no defaults to prevent silent bugs

variable "aws_region" {
  type        = string
  description = "AWS region to build AMI in"
}

variable "instance_type" {
  type        = string
  description = "EC2 instance type for building (recommend t3.large for faster builds)"
}

variable "ami_prefix" {
  type        = string
  description = "Prefix for AMI names"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID to launch builder in (use empty string for default VPC)"
}

variable "subnet_id" {
  type        = string
  description = "Subnet ID to launch builder in (use empty string for default)"
}
