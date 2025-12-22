# Log Aggregation Module - CloudWatch Alarms
#
# Creates:
# - Firehose delivery lag alarm (logs not reaching S3)
# - WAF Firehose delivery lag alarm (if WAF logging enabled)
# - SQS DLQ alarm (failed message processing)

# ------------------------------------------------------------------------------
# SNS Topic for Alarm Notifications (optional)
# ------------------------------------------------------------------------------

resource "aws_sns_topic" "log_alarms" {
  count = var.enable_log_aggregation && var.enable_alarms ? 1 : 0

  name              = "${var.name_prefix}-log-alarms-${var.environment}"
  kms_master_key_id = "alias/aws/sns"

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-log-alarms-${var.environment}"
  })
}

resource "aws_sns_topic_subscription" "log_alarms_email" {
  count = var.enable_log_aggregation && var.enable_alarms && var.alarm_email != "" ? 1 : 0

  topic_arn = aws_sns_topic.log_alarms[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ------------------------------------------------------------------------------
# Firehose Delivery Lag Alarm
# Alerts if logs are not being delivered to S3 within 15 minutes
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "firehose_delivery_lag" {
  count = var.enable_log_aggregation && var.enable_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-firehose-delivery-lag-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "DeliveryToS3.DataFreshness"
  namespace           = "AWS/Firehose"
  period              = 300
  statistic           = "Average"
  threshold           = 900 # 15 minutes in seconds
  alarm_description   = "Firehose log delivery lag exceeds 15 minutes"
  treat_missing_data  = "notBreaching"

  dimensions = {
    DeliveryStreamName = aws_kinesis_firehose_delivery_stream.logs[0].name
  }

  alarm_actions = var.alarm_email != "" ? [aws_sns_topic.log_alarms[0].arn] : []
  ok_actions    = var.alarm_email != "" ? [aws_sns_topic.log_alarms[0].arn] : []

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-firehose-delivery-lag-${var.environment}"
  })
}

# ------------------------------------------------------------------------------
# WAF Firehose Delivery Lag Alarm
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "waf_firehose_delivery_lag" {
  count = var.enable_log_aggregation && var.enable_alarms && var.enable_waf_logging ? 1 : 0

  alarm_name          = "${var.name_prefix}-waf-firehose-delivery-lag-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "DeliveryToS3.DataFreshness"
  namespace           = "AWS/Firehose"
  period              = 300
  statistic           = "Average"
  threshold           = 900 # 15 minutes in seconds
  alarm_description   = "WAF Firehose log delivery lag exceeds 15 minutes"
  treat_missing_data  = "notBreaching"

  dimensions = {
    DeliveryStreamName = aws_kinesis_firehose_delivery_stream.waf[0].name
  }

  alarm_actions = var.alarm_email != "" ? [aws_sns_topic.log_alarms[0].arn] : []
  ok_actions    = var.alarm_email != "" ? [aws_sns_topic.log_alarms[0].arn] : []

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-waf-firehose-delivery-lag-${var.environment}"
  })
}

# ------------------------------------------------------------------------------
# SQS Dead-Letter Queue Alarm
# Alerts if any messages end up in the DLQ (failed processing)
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "sqs_dlq_messages" {
  count = var.enable_log_aggregation && var.enable_alarms && var.enable_sqs_notifications ? 1 : 0

  alarm_name          = "${var.name_prefix}-log-dlq-messages-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Messages in log notification dead-letter queue"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.log_notifications_dlq[0].name
  }

  alarm_actions = var.alarm_email != "" ? [aws_sns_topic.log_alarms[0].arn] : []
  ok_actions    = var.alarm_email != "" ? [aws_sns_topic.log_alarms[0].arn] : []

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-log-dlq-messages-${var.environment}"
  })
}
