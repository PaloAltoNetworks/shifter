variable "aws_region" {
  type        = string
  default     = "us-east-2"
  description = "AWS region to build AMI in"
}

variable "instance_type" {
  type        = string
  default     = "t3.medium"
  description = "EC2 instance type for building"
}

variable "ami_prefix" {
  type        = string
  default     = "shifter"
  description = "Prefix for AMI names"
}

variable "vpc_id" {
  type        = string
  default     = ""
  description = "VPC ID to launch builder in (empty = default VPC)"
}

variable "subnet_id" {
  type        = string
  default     = ""
  description = "Subnet ID to launch builder in (empty = default)"
}
