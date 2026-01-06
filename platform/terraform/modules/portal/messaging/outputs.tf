output "sns_topic_arn" {
  description = "ARN of the SNS topic for range events"
  value       = aws_sns_topic.range_events.arn
}

output "sqs_queue_urls" {
  description = "Map of consumer name to SQS queue URL"
  value       = { for k, v in aws_sqs_queue.tasks : k => v.url }
}

output "sqs_queue_arns" {
  description = "Map of consumer name to SQS queue ARN"
  value       = { for k, v in aws_sqs_queue.tasks : k => v.arn }
}

output "dlq_queue_urls" {
  description = "Map of consumer name to DLQ URL"
  value       = { for k, v in aws_sqs_queue.dlq : k => v.url }
}

output "dlq_queue_arns" {
  description = "Map of consumer name to DLQ ARN"
  value       = { for k, v in aws_sqs_queue.dlq : k => v.arn }
}
