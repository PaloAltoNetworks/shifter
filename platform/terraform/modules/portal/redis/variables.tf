# Redis module variables - NO DEFAULTS

variable "name_prefix" {
  description = "Prefix for resource names (e.g., prod-portal)"
  type        = string
}

variable "iam_name_prefix" {
  description = "Prefix for IAM resource names. Defaults to name_prefix for legacy callers."
  type        = string
  default     = null
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

variable "secrets_kms_key_arn" {
  description = "ARN of the portal Secrets Manager CMK used to encrypt the Redis AUTH token secret. Required when enable_replication is true (the AUTH/in-transit path stores the token in Secrets Manager); ignored on the single-node path. Default empty so non-replication callers need not pass it."
  type        = string
  default     = ""
}

variable "redis_at_rest_kms_key_arn" {
  description = "ARN of the dedicated Redis data-at-rest CMK used to encrypt the replication group's storage and its automated snapshots (#1059). Required when enable_replication is true (enforced by a precondition on the replication group); ignored on the single-node dev-only plaintext path. Kept distinct from secrets_kms_key_arn, which encrypts the AUTH token secret, not the cache storage. Default empty so non-replication callers need not pass it."
  type        = string
  default     = ""
}

variable "cloudwatch_logs_kms_key_arn" {
  description = "ARN of the dedicated CloudWatch Logs CMK used to encrypt the AUTH rotation Lambda's log group. Distinct from secrets_kms_key_arn: the Secrets Manager CMK is scoped (kms:ViaService) to secretsmanager only and rejects use by the CloudWatch Logs service, so the log group must be encrypted with a key whose policy grants logs.<region>.amazonaws.com. Required when the rotation path is enabled; default empty for non-rotation callers."
  type        = string
  default     = ""
}

variable "permissions_boundary_arn" {
  description = "ARN of the CI permissions boundary applied to IAM roles created by this module (the AUTH rotation Lambda role). The deploy role's iam:CreateRole is conditioned on this exact boundary, so it must be passed for the rotation role to be creatable. Default empty for callers/paths that create no roles."
  type        = string
  default     = ""
}

variable "redis_auth_rotation_days" {
  description = "Automatic rotation interval (days) for the Redis AUTH token secret (#159). Bounded to at most 90 days to stay within the security rotation window (CKV_AWS_304); applies only on the rotation-enabled path."
  type        = number
  default     = 90

  validation {
    condition     = var.redis_auth_rotation_days >= 1 && var.redis_auth_rotation_days <= 90
    error_message = "redis_auth_rotation_days must be between 1 and 90 (the security rotation window)."
  }
}

variable "enable_auth_rotation" {
  description = "Enable automatic Redis AUTH token rotation (#159). Set by the root to enable_autoscaling: rotation is only scheduled where the portal runs on a refreshable ASG, because ElastiCache ROTATE keeps only the two newest tokens and a consumer that never rehydrates would lose auth at the next rotation. The single-instance path uses the documented manual rotation instead. Static (not a computed value) so it can gate resource count."
  type        = bool
  default     = false
}

variable "portal_asg_name" {
  description = "Name of the portal ASG the Redis rotation Lambda refreshes (autoscaling:StartInstanceRefresh) so containers rehydrate the new AUTH token after promotion. Wired by the root to module.ec2.asg_name when enable_auth_rotation is true; used only in the Lambda environment and IAM scope, never in a resource count."
  type        = string
  default     = ""
}

variable "is_active_channel_backend" {
  description = "True when this Redis is the active Django Channels backend for the environment (the env-root enable_redis posture). When true, the module requires the AUTH + in-transit encryption path (enable_replication = true); the single-node path is dev-only plaintext and must not back a live channel layer."
  type        = bool
  default     = false
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

variable "apply_immediately" {
  description = "Apply ElastiCache modifications (node type, engine, params) during the deploy instead of queueing them for the maintenance window. Required input; environments choose explicitly."
  type        = bool
}
