# Log Aggregation Module - Customer-Managed KMS Key
#
# Single CMK shared by the module's CloudWatch log group, Kinesis Firehose
# streams, SQS queues, and the logs S3 bucket. Satisfies ADR-004-R11 /
# Checkov CKV_AWS_158 / CKV_AWS_240 / CKV_AWS_241 / CKV_AWS_27 / CKV_AWS_145.
#
# The key policy grants the AWS service principals for CloudWatch Logs and
# S3 the operations they need, scoped to this account. SQS and Kinesis
# Firehose call KMS as the deploying principal (the Firehose role or the
# producer), so they reuse the broad root-account grant.

resource "aws_kms_key" "log_aggregation" {
  count = var.enable_log_aggregation ? 1 : 0

  description             = "CMK for shifter log-aggregation module (CW Logs, Firehose, SQS, S3)"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableRootAccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowCloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${var.aws_region}.amazonaws.com" }
        Action = [
          "kms:Encrypt*",
          "kms:Decrypt*",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey",
        ]
        Resource = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
          }
        }
      },
      {
        Sid       = "AllowS3ServiceForLogsBucket"
        Effect    = "Allow"
        Principal = { Service = "s3.amazonaws.com" }
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      },
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-log-aggregation-cmk-${var.environment}"
  })
}

resource "aws_kms_alias" "log_aggregation" {
  count = var.enable_log_aggregation ? 1 : 0

  name          = "alias/${var.name_prefix}-log-aggregation-${var.environment}"
  target_key_id = aws_kms_key.log_aggregation[0].key_id
}
