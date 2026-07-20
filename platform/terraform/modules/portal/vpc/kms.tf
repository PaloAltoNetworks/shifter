# Portal-VPC Module - Customer-Managed KMS Key for CloudWatch Logs
#
# CMK so the VPC flow logs log group meets Checkov CKV_AWS_158.

data "aws_caller_identity" "kms_account" {}

data "aws_region" "kms_region" {}

resource "aws_kms_key" "cloudwatch_logs" {
  description             = "CMK for shifter portal-vpc CloudWatch logs (CKV_AWS_158)"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableRootAccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.kms_account.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowCloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${data.aws_region.kms_region.name}.amazonaws.com" }
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
            "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${data.aws_region.kms_region.name}:${data.aws_caller_identity.kms_account.account_id}:*"
          }
        }
      },
    ]
  })

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-portal-vpc-cw-logs-cmk"
    Module = "vpc"
  })
}

resource "aws_kms_alias" "cloudwatch_logs" {
  name          = "alias/${var.name_prefix}-portal-vpc-cw-logs"
  target_key_id = aws_kms_key.cloudwatch_logs.key_id
}
