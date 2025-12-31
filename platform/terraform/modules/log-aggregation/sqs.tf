# Log Aggregation Module - SQS Queue for Log Notifications
#
# Creates:
# - SQS queue for S3 object notifications (XDR/XSIAM polling)
# - Dead-letter queue for failed messages
# - Queue policies for S3 to send notifications
# - S3 bucket notification configuration

# ------------------------------------------------------------------------------
# Dead-Letter Queue
# ------------------------------------------------------------------------------

resource "aws_sqs_queue" "log_notifications_dlq" {
  count = var.enable_log_aggregation && var.enable_sqs_notifications ? 1 : 0

  name                      = "${var.name_prefix}-log-notifications-dlq-${var.environment}"
  message_retention_seconds = 1209600 # 14 days

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-log-notifications-dlq-${var.environment}"
  })
}

# ------------------------------------------------------------------------------
# Main SQS Queue for Log Notifications
# ------------------------------------------------------------------------------

resource "aws_sqs_queue" "log_notifications" {
  count = var.enable_log_aggregation && var.enable_sqs_notifications ? 1 : 0

  name                       = "${var.name_prefix}-log-notifications-${var.environment}"
  visibility_timeout_seconds = 300
  message_retention_seconds  = 345600 # 4 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.log_notifications_dlq[0].arn
    maxReceiveCount     = 3
  })

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-log-notifications-${var.environment}"
  })
}

# ------------------------------------------------------------------------------
# SQS Queue Policy - Allow S3 to send messages
# ------------------------------------------------------------------------------

resource "aws_sqs_queue_policy" "log_notifications" {
  count = var.enable_log_aggregation && var.enable_sqs_notifications ? 1 : 0

  queue_url = aws_sqs_queue.log_notifications[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowS3Notifications"
        Effect = "Allow"
        Principal = {
          Service = "s3.amazonaws.com"
        }
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.log_notifications[0].arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = aws_s3_bucket.logs[0].arn
          }
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# S3 Bucket Notification to SQS
# ------------------------------------------------------------------------------

resource "aws_s3_bucket_notification" "log_notifications" {
  count = var.enable_log_aggregation && var.enable_sqs_notifications ? 1 : 0

  bucket = aws_s3_bucket.logs[0].id

  queue {
    queue_arn = aws_sqs_queue.log_notifications[0].arn
    events    = ["s3:ObjectCreated:*"]
  }

  depends_on = [aws_sqs_queue_policy.log_notifications]
}
