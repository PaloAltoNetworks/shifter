# Log Aggregation Module - XDR Cross-Account Access
#
# Creates:
# - IAM role for Cortex XDR cross-account access (conditional)
# - IAM policy for XDR to read S3 and consume SQS

# ------------------------------------------------------------------------------
# IAM Role for XDR Cross-Account Access
# ------------------------------------------------------------------------------

resource "aws_iam_role" "xdr_access" {
  count = var.enable_log_aggregation && var.xdr_aws_account_id != "" ? 1 : 0

  name = "${var.name_prefix}-xdr-access-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${var.xdr_aws_account_id}:root"
        }
        Action = "sts:AssumeRole"
        Condition = {
          StringEquals = {
            "sts:ExternalId" = var.xdr_external_id
          }
        }
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-xdr-access-${var.environment}"
  })
}

# ------------------------------------------------------------------------------
# IAM Policy for XDR - S3 Read Access
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "xdr_s3_read" {
  count = var.enable_log_aggregation && var.xdr_aws_account_id != "" ? 1 : 0

  name = "s3-read"
  role = aws_iam_role.xdr_access[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion"
        ]
        Resource = "${aws_s3_bucket.logs[0].arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = aws_s3_bucket.logs[0].arn
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# IAM Policy for XDR - SQS Access
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "xdr_sqs" {
  count = var.enable_log_aggregation && var.xdr_aws_account_id != "" && var.enable_sqs_notifications ? 1 : 0

  name = "sqs-consume"
  role = aws_iam_role.xdr_access[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:ChangeMessageVisibility",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl"
        ]
        Resource = aws_sqs_queue.log_notifications[0].arn
      }
    ]
  })
}
