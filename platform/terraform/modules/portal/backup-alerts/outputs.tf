# SPDX-FileCopyrightText: 2026 Palo Alto Networks, Inc.
# SPDX-License-Identifier: MIT

# Backup-alerts module outputs

output "topic_arn" {
  description = "ARN of the SNS topic that receives RDS backup/availability/failure events"
  value       = aws_sns_topic.this.arn
}

output "kms_key_arn" {
  description = "ARN of the CMK used to encrypt the backup-alerts topic"
  value       = aws_kms_key.this.arn
}

output "event_subscription_name" {
  description = "Name of the RDS event subscription, or null when no DB instances were supplied"
  value       = length(aws_db_event_subscription.this) > 0 ? aws_db_event_subscription.this[0].name : null
}
