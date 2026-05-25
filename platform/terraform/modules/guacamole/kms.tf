# Guacamole Module - Customer-Managed KMS Key for CloudWatch Logs
#
# CMK so the guacd / guacamole_client / RDS log groups meet Checkov CKV_AWS_158.
# Reuses the existing data.aws_caller_identity.current and data.aws_region.current
# data sources declared in main.tf.

resource "aws_kms_key" "cloudwatch_logs" {
  description             = "CMK for shifter guacamole CloudWatch logs (CKV_AWS_158)"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableRootAccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowCloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${local.region}.amazonaws.com" }
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
            "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${local.region}:${local.account_id}:*"
          }
        }
      },
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-cw-logs-cmk"
  })
}

resource "aws_kms_alias" "cloudwatch_logs" {
  name          = "alias/${var.name_prefix}-guacamole-cw-logs"
  target_key_id = aws_kms_key.cloudwatch_logs.key_id
}
