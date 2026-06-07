# Customer-Managed KMS Key for env-direct CloudWatch log groups
#
# Used by the env-direct Bedrock log group (and any future env-direct log
# group). Module-managed log groups carry their own per-module CMKs.

resource "aws_kms_key" "cloudwatch_logs" {
  description             = "CMK for shifter-prod env-direct CloudWatch logs (CKV_AWS_158)"
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
    ]
  })

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-cw-logs-cmk"
  })
}

resource "aws_kms_alias" "cloudwatch_logs" {
  name          = "alias/${local.name_prefix}-cw-logs"
  target_key_id = aws_kms_key.cloudwatch_logs.key_id
}
