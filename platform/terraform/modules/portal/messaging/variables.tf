variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
}

variable "consumers" {
  description = "List of consumer names (creates one SQS queue per consumer)"
  type        = list(string)
}

variable "visibility_timeout_seconds" {
  description = "SQS visibility timeout in seconds"
  type        = number
}

variable "message_retention_seconds" {
  description = "SQS message retention period in seconds"
  type        = number
}

# ------------------------------------------------------------------------------
# Dead Letter Queue Configuration
# ------------------------------------------------------------------------------

variable "enable_dlq" {
  description = "Enable dead letter queues for failed messages"
  type        = bool
}

variable "dlq_max_receive_count" {
  description = "Number of times a message can be received before moving to DLQ"
  type        = number
}

variable "dlq_message_retention_seconds" {
  description = "DLQ message retention period in seconds"
  type        = number
}

# ------------------------------------------------------------------------------
# CloudWatch Alarm Configuration
# ------------------------------------------------------------------------------

variable "enable_alarms" {
  description = "Enable CloudWatch alarms for queue monitoring"
  type        = bool
}

variable "alarm_queue_depth_threshold" {
  description = "Alarm threshold for approximate number of messages in queue"
  type        = number
}

variable "alarm_message_age_threshold" {
  description = "Alarm threshold for oldest message age in seconds"
  type        = number
}

variable "alarm_dlq_threshold" {
  description = "Alarm threshold for messages in DLQ"
  type        = number
}

variable "alarm_actions" {
  description = "List of ARNs to notify when alarm triggers (e.g., SNS topic ARNs)"
  type        = list(string)
}
