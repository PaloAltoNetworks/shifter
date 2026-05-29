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
  description = "CIDR blocks allowed to access Redis. Prefer allowed_security_group_ids; CIDRs are kept for callers that genuinely cannot pass an SG."
  type        = list(string)
  default     = []
}

variable "allowed_security_group_ids" {
  description = "Security group IDs allowed to access Redis. Preferred over allowed_cidr_blocks for microsegmentation. At least one of allowed_cidr_blocks or allowed_security_group_ids must be non-empty (enforced by a precondition on the Redis instance)."
  type        = list(string)
  default     = []
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

variable "enable_replication" {
  description = "Enable replication group with automatic failover (false for single-node)"
  type        = bool
}

# ------------------------------------------------------------------------------
# Alarm Configuration
# ------------------------------------------------------------------------------

variable "enable_alarms" {
  description = "Enable CloudWatch alarms for Redis metrics"
  type        = bool
  default     = false
}

variable "alarm_actions" {
  description = "List of ARNs to notify when alarm triggers (e.g., SNS topic)"
  type        = list(string)
  default     = []
}

variable "alarm_cpu_threshold" {
  description = "CPU utilization threshold for alarm (percent)"
  type        = number
  default     = 75
}

variable "alarm_memory_threshold" {
  description = "Memory utilization threshold for alarm (percent)"
  type        = number
  default     = 80
}

variable "alarm_connections_threshold" {
  description = "Current connections threshold for alarm"
  type        = number
  default     = 1000
}
