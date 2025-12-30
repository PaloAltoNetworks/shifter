# CloudWatch Alarms for Range VPC
#
# Capacity alarms for NGFW infrastructure to alert before hitting limits.

# ------------------------------------------------------------------------------
# KMS Key for SNS Encryption
# ------------------------------------------------------------------------------
resource "aws_kms_key" "sns" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  description             = "KMS key for SNS topic encryption in ${var.name_prefix}"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowRootAccount"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "AllowCloudWatchAlarms"
        Effect = "Allow"
        Principal = {
          Service = "cloudwatch.amazonaws.com"
        }
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey*"
        ]
        Resource = "*"
      },
      {
        Sid    = "AllowSNSService"
        Effect = "Allow"
        Principal = {
          Service = "sns.amazonaws.com"
        }
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey*"
        ]
        Resource = "*"
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-sns-key"
  })
}

resource "aws_kms_alias" "sns" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  name          = "alias/${var.name_prefix}-sns"
  target_key_id = aws_kms_key.sns[0].key_id
}

# ------------------------------------------------------------------------------
# NGFW Capacity Alarm
# ------------------------------------------------------------------------------
# Alerts when NGFWCount custom metric exceeds 400 (80% of ~500 capacity)
# Allows time for capacity planning before hitting subnet limits.
#
# Note: The NGFWCount metric is published by the NGFW reconciliation job.

resource "aws_sns_topic" "ngfw_capacity" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  name              = "${var.name_prefix}-ngfw-capacity-alerts"
  kms_master_key_id = aws_kms_key.sns[0].arn

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
