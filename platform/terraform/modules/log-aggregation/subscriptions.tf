# Log Aggregation Module - CloudWatch Log Subscriptions
#
# Creates:
# - IAM role for CloudWatch Logs to write to Firehose
# - Subscription filters for each source log group

# ------------------------------------------------------------------------------
# IAM Role for CloudWatch Logs to Firehose
# ------------------------------------------------------------------------------

resource "aws_iam_role" "cloudwatch_to_firehose" {
  count = var.enable_log_aggregation && length(var.source_log_group_names) > 0 ? 1 : 0

  name = "${var.name_prefix}-cw-to-firehose-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "logs.${var.aws_region}.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-cw-to-firehose-${var.environment}"
  })
}

resource "aws_iam_role_policy" "cloudwatch_to_firehose" {
  count = var.enable_log_aggregation && length(var.source_log_group_names) > 0 ? 1 : 0

  name = "firehose-put"
  role = aws_iam_role.cloudwatch_to_firehose[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "firehose:PutRecord",
          "firehose:PutRecordBatch"
        ]
        Resource = aws_kinesis_firehose_delivery_stream.logs[0].arn
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# CloudWatch Log Subscription Filters
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_subscription_filter" "to_firehose" {
  for_each = var.enable_log_aggregation ? toset(var.source_log_group_names) : toset([])

  name            = "to-firehose"
  log_group_name  = each.value
  filter_pattern  = "" # All logs
  destination_arn = aws_kinesis_firehose_delivery_stream.logs[0].arn
  role_arn        = aws_iam_role.cloudwatch_to_firehose[0].arn
}
