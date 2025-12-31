# Redis module variables - NO DEFAULTS

variable "name_prefix" {
  description = "Prefix for resource names (e.g., prod-portal)"
  type        = string
}

variable "vpc_id" {
  description = "ID of the VPC"
  type        = string
}

variable "subnet_ids" {
  description = "List of subnet IDs for the ElastiCache subnet group"
  type        = list(string)
}

variable "allowed_cidr_blocks" {
  description = "CIDR blocks allowed to access Redis"
  type        = list(string)
}

variable "node_type" {
  description = "ElastiCache node type (e.g., cache.t3.micro, cache.t3.medium)"
  type        = string
}

variable "engine_version" {
  description = "Redis engine version"
  type        = string
}

variable "tags" {
  description = "Common tags to apply to all resources"
  type        = map(string)
}
