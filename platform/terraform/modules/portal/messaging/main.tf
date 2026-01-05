# Messaging module - SNS/SQS for event-driven communication
#
# Creates:
# - SNS topic for range events (provisioner publishes here)
# - SQS queues for each consumer (cms, engine, mc)
# - SNS subscriptions (fan-out to all queues)
# - SQS policies allowing SNS to send messages

locals {
  common_tags = merge(var.tags, {
    Module = "messaging"
  })
}

# ------------------------------------------------------------------------------
# SNS Topic for Range Events
# ------------------------------------------------------------------------------

resource "aws_sns_topic" "range_events" {
  name = "${var.name_prefix}-range-events"
  tags = local.common_tags
}

# ------------------------------------------------------------------------------
# Dead Letter Queues (DLQs)
# ------------------------------------------------------------------------------

resource "aws_sqs_queue" "dlq" {
  for_each = var.enable_dlq ? toset(var.consumers) : []

  name                      = "${var.name_prefix}-${each.key}-tasks-dlq"
  message_retention_seconds = var.dlq_message_retention_seconds
  tags                      = local.common_tags
}

# ------------------------------------------------------------------------------
# SQS Queues for Each Consumer
# ------------------------------------------------------------------------------

resource "aws_sqs_queue" "tasks" {
  for_each = toset(var.consumers)

  name                       = "${var.name_prefix}-${each.key}-tasks"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds
  tags                       = local.common_tags

  # Redrive policy: send failed messages to DLQ after max_receive_count attempts
  redrive_policy = var.enable_dlq ? jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = var.dlq_max_receive_count
  }) : null
}

# ------------------------------------------------------------------------------
# SNS Subscriptions (Fan-out to All Queues)
# ------------------------------------------------------------------------------

resource "aws_sns_topic_subscription" "sqs" {
  for_each = aws_sqs_queue.tasks

  topic_arn = aws_sns_topic.range_events.arn
  protocol  = "sqs"
  endpoint  = each.value.arn
}

# ------------------------------------------------------------------------------
# SQS Policies (Allow SNS to Send Messages)
# ------------------------------------------------------------------------------

resource "aws_sqs_queue_policy" "sns_to_sqs" {
  for_each = aws_sqs_queue.tasks

  queue_url = each.value.url

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = each.value.arn
      Condition = {
        ArnEquals = { "aws:SourceArn" = aws_sns_topic.range_events.arn }
      }
    }]
  })
}

# ------------------------------------------------------------------------------
# CloudWatch Alarms - Queue Depth
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "queue_depth" {
  for_each = var.enable_alarms ? aws_sqs_queue.tasks : {}

  alarm_name          = "${var.name_prefix}-${each.key}-queue-depth"
  alarm_description   = "Alarm when ${each.key} queue has too many messages waiting"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Average"
  threshold           = var.alarm_queue_depth_threshold

  dimensions = {
    QueueName = each.value.name
  }

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions
  tags          = local.common_tags
}

# ------------------------------------------------------------------------------
# CloudWatch Alarms - Message Age
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "message_age" {
  for_each = var.enable_alarms ? aws_sqs_queue.tasks : {}

  alarm_name          = "${var.name_prefix}-${each.key}-message-age"
  alarm_description   = "Alarm when oldest message in ${each.key} queue is too old"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = var.alarm_message_age_threshold

  dimensions = {
    QueueName = each.value.name
  }

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions
  tags          = local.common_tags
}

# ------------------------------------------------------------------------------
# CloudWatch Alarms - Dead Letter Queue Messages
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  for_each = var.enable_alarms && var.enable_dlq ? aws_sqs_queue.dlq : {}

  alarm_name          = "${var.name_prefix}-${each.key}-dlq-messages"
  alarm_description   = "Alarm when messages appear in ${each.key} dead letter queue"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = var.alarm_dlq_threshold

  dimensions = {
    QueueName = each.value.name
  }

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions
  tags          = local.common_tags
}
