variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "name_prefix" {
  description = "Prefix for resource names."
  type        = string
}

variable "common_labels" {
  description = "Labels to apply to resources."
  type        = map(string)
}

variable "platform_event_subscriptions" {
  description = "Set of worker names; one Pub/Sub subscription is created per entry."
  type        = set(string)
}

# ------------------------------------------------------------------------------
# Dead-Letter Configuration
# ------------------------------------------------------------------------------

variable "enable_dlq" {
  description = "Enable the dead-letter topic, retention subscription, and dead_letter_policy on each source subscription. Parity with AWS enable_dlq."
  type        = bool
  default     = true
}

variable "max_delivery_attempts" {
  description = "Number of delivery attempts before a message is forwarded to the dead-letter topic. GCP minimum is 5."
  type        = number
  default     = 5

  validation {
    condition     = var.max_delivery_attempts >= 5 && var.max_delivery_attempts <= 100
    error_message = "max_delivery_attempts must be between 5 and 100 (GCP Pub/Sub constraint)."
  }
}

variable "dlq_retention" {
  description = "Message retention duration for the dead-letter subscription. Format: '<seconds>s' (e.g. '1209600s' = 14 days). Parity with AWS dlq_message_retention_seconds."
  type        = string
  default     = "1209600s"
}

# ------------------------------------------------------------------------------
# Retry Policy Configuration
# ------------------------------------------------------------------------------

variable "retry_min_backoff" {
  description = "Minimum backoff for the subscription retry policy. Format: '<seconds>s'."
  type        = string
  default     = "10s"
}

variable "retry_max_backoff" {
  description = "Maximum backoff for the subscription retry policy. Format: '<seconds>s'."
  type        = string
  default     = "600s"
}

# ------------------------------------------------------------------------------
# Cloud Monitoring Alert Configuration
# ------------------------------------------------------------------------------

variable "enable_alarms" {
  description = "Enable Cloud Monitoring alert policies for subscription monitoring. Parity with AWS enable_alarms."
  type        = bool
  default     = false
}

variable "alarm_queue_depth_threshold" {
  description = "Alert threshold for num_undelivered_messages on source subscriptions. Parity with AWS alarm_queue_depth_threshold."
  type        = number
  default     = 100
}

variable "alarm_message_age_threshold" {
  description = "Alert threshold in seconds for oldest_unacked_message_age on source subscriptions. Parity with AWS alarm_message_age_threshold."
  type        = number
  default     = 300
}

variable "alarm_dlq_threshold" {
  description = "Alert threshold for messages visible in the dead-letter subscription. Parity with AWS alarm_dlq_threshold."
  type        = number
  default     = 1
}

variable "notification_channels" {
  description = "List of Cloud Monitoring notification channel resource IDs to notify when an alert fires. Parity with AWS alarm_actions."
  type        = list(string)
  default     = []
}
