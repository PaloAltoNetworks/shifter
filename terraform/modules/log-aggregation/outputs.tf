# Log Aggregation Module Outputs

output "logs_bucket_name" {
  description = "Name of the S3 bucket for logs"
  value       = var.enable_log_aggregation ? aws_s3_bucket.logs[0].id : ""
}

output "logs_bucket_arn" {
  description = "ARN of the S3 bucket for logs"
  value       = var.enable_log_aggregation ? aws_s3_bucket.logs[0].arn : ""
}

output "sqs_queue_url" {
  description = "URL of the SQS queue for log notifications"
  value       = var.enable_log_aggregation && var.enable_sqs_notifications ? aws_sqs_queue.log_notifications[0].url : ""
}

output "sqs_queue_arn" {
  description = "ARN of the SQS queue for log notifications"
  value       = var.enable_log_aggregation && var.enable_sqs_notifications ? aws_sqs_queue.log_notifications[0].arn : ""
}

output "firehose_arn" {
  description = "ARN of the Kinesis Firehose delivery stream"
  value       = var.enable_log_aggregation ? aws_kinesis_firehose_delivery_stream.logs[0].arn : ""
}

output "firehose_name" {
  description = "Name of the Kinesis Firehose delivery stream"
  value       = var.enable_log_aggregation ? aws_kinesis_firehose_delivery_stream.logs[0].name : ""
}

output "xdr_role_arn" {
  description = "ARN of the XDR cross-account access role"
  value       = var.enable_log_aggregation && var.xdr_aws_account_id != "" ? aws_iam_role.xdr_access[0].arn : ""
}

output "waf_firehose_arn" {
  description = "ARN of the WAF Kinesis Firehose delivery stream"
  value       = var.enable_log_aggregation && var.enable_waf_logging ? aws_kinesis_firehose_delivery_stream.waf[0].arn : ""
}
