variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
}

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "network_id" {
  description = "VPC network self-link (must have Private Services Access configured)"
  type        = string
}

variable "tier" {
  description = "BASIC (single node, dev) or STANDARD_HA (replicated, prod)"
  type        = string
  default     = "BASIC"
}

variable "memory_size_gb" {
  description = "Redis memory in GB"
  type        = number
  default     = 1
}

variable "redis_version" {
  description = "Redis version"
  type        = string
  default     = "REDIS_7_2"
}

variable "auth_enabled" {
  description = "Require AUTH password for connections"
  type        = bool
  default     = true
}

variable "labels" {
  description = "Labels to apply"
  type        = map(string)
  default     = {}
}
