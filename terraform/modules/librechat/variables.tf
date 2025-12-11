# LibreChat Module Variables

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID to deploy into"
  type        = string
}

variable "private_route_table_id" {
  description = "Route table ID for the private subnet (routes to NAT gateway)"
  type        = string
}

variable "availability_zone" {
  description = "Availability zone for the LibreChat subnet"
  type        = string
}

variable "subnet_cidr" {
  description = "CIDR block for LibreChat subnet (e.g., 10.0.10.0/24)"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.small"
}

variable "root_volume_size" {
  description = "Size of root EBS volume in GB"
  type        = number
  default     = 30
}

variable "data_volume_size" {
  description = "Size of data EBS volume for MongoDB in GB"
  type        = number
  default     = 50
}

variable "app_title" {
  description = "LibreChat application title"
  type        = string
  default     = "Shifter Chat"
}

variable "allow_registration" {
  description = "Allow new user registration (set false after admin created)"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

