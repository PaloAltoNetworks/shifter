# Pulumi Provisioner Module - CloudWatch Alarms
#
# Creates:
# - SNS topic for range launch failure notifications
# - CloudWatch metric filter to detect failures in provisioner logs
# - CloudWatch alarm that triggers when launch failures occur

# ------------------------------------------------------------------------------
# SNS Topic for Range Launch Failure Notifications
# ------------------------------------------------------------------------------

resource "aws_sns_topic" "range_launch_failures" {
  count = var.enable_alarms ? 1 : 0

  name              = "${var.name_prefix}-range-launch-failures-${var.environment}"
  kms_master_key_id = "alias/aws/sns"

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-range-launch-failures-${var.environment}"
  })
}

resource "aws_sns_topic_subscription" "range_launch_failures_email" {
  count = var.enable_alarms && var.alarm_email != "" ? 1 : 0

  topic_arn = aws_sns_topic.range_launch_failures[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ------------------------------------------------------------------------------
# CloudWatch Metric Filter for Range Launch Failures
# Detects "Operation failed" or "Provision failed" messages in provisioner logs
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_metric_filter" "range_launch_failures" {
  count = var.enable_alarms ? 1 : 0

  name           = "${var.name_prefix}-range-launch-failures"
  log_group_name = aws_cloudwatch_log_group.ecs.name
  pattern        = "?\"Operation failed\" ?\"Provision failed\""

  metric_transformation {
    name          = "RangeLaunchFailures"
    namespace     = "Shifter/RangeProvisioning"
    value         = "1"
    default_value = "0"
  }
}

# ------------------------------------------------------------------------------
# CloudWatch Alarm for Range Launch Failures
# Alerts when any range launch failure is detected
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "range_launch_failures" {
  count = var.enable_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-range-launch-failures-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "RangeLaunchFailures"
  namespace           = "Shifter/RangeProvisioning"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Range launch failure detected in ${var.environment} environment"
  treat_missing_data  = "notBreaching"

  alarm_actions = var.alarm_email != "" ? [aws_sns_topic.range_launch_failures[0].arn] : []
  ok_actions    = var.alarm_email != "" ? [aws_sns_topic.range_launch_failures[0].arn] : []

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-range-launch-failures-${var.environment}"
  })
}
