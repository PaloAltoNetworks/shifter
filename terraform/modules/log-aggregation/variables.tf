# Log Aggregation Module Variables
#
# Note: No defaults for required variables per codebase convention

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "environment" {
  description = "Environment name (prod, dev, etc.)"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "log_retention_days" {
  description = "Days to retain logs in S3"
  type        = number
}

variable "enable_log_aggregation" {
  description = "Enable log aggregation infrastructure (S3, SQS, Firehose)"
  type        = bool
}

variable "enable_sqs_notifications" {
  description = "Enable SQS notifications for XDR/XSIAM integration"
  type        = bool
  default     = true
}

variable "enable_alb_access_logs" {
  description = "Enable ALB access logs (adds bucket policy for ALB service)"
  type        = bool
  default     = false
}

variable "enable_waf_logging" {
  description = "Enable WAF logging via dedicated Firehose stream"
  type        = bool
  default     = false
}

variable "source_log_group_names" {
  description = "List of CloudWatch log group names to subscribe to Firehose"
  type        = list(string)
  default     = []
}

variable "enable_alarms" {
  description = "Enable CloudWatch alarms for log aggregation"
  type        = bool
  default     = false
}

variable "alarm_email" {
  description = "Email address for alarm notifications (leave empty to skip)"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
