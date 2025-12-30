# CloudWatch Alarms for Range VPC
#
# Capacity alarms for NGFW infrastructure to alert before hitting limits.

# ------------------------------------------------------------------------------
# NGFW Capacity Alarm
# ------------------------------------------------------------------------------
# Alerts when NGFWCount custom metric exceeds 400 (80% of ~500 capacity)
# Allows time for capacity planning before hitting subnet limits.
#
# Note: The NGFWCount metric is published by the NGFW reconciliation job.

resource "aws_sns_topic" "ngfw_capacity" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  name = "${var.name_prefix}-ngfw-capacity-alerts"

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ngfw-capacity-alerts"
  })
}

resource "aws_cloudwatch_metric_alarm" "ngfw_count" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  alarm_name          = "${var.name_prefix}-ngfw-count-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "NGFWCount"
  namespace           = "Shifter/NGFW"
  period              = 300
  statistic           = "Maximum"
  threshold           = 400
  alarm_description   = "NGFW count exceeds 400 (80% of ~500 capacity). Plan capacity expansion."
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.ngfw_capacity[0].arn]
  ok_actions    = [aws_sns_topic.ngfw_capacity[0].arn]

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ngfw-count-alarm"
  })
}
