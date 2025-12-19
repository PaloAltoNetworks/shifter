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

variable "source_log_group_names" {
  description = "List of CloudWatch log group names to subscribe to Firehose"
  type        = list(string)
  default     = []
}

variable "xdr_aws_account_id" {
  description = "AWS account ID for XDR cross-account access (empty if not configured)"
  type        = string
  default     = ""
}

variable "xdr_external_id" {
  description = "External ID for XDR cross-account role assumption"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
