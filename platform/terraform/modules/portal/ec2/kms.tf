# Portal-EC2 Module - Customer-Managed KMS Key for CloudWatch Logs
#
# Dedicated CMK so the portal CloudWatch log group meets Checkov CKV_AWS_158.
# The key policy grants the CloudWatch Logs service in this region the
# operations it needs, scoped to log streams in this account.

resource "aws_kms_key" "cloudwatch_logs" {
  description             = "CMK for shifter portal-ec2 CloudWatch logs (CKV_AWS_158)"
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
        Principal = { Service = "logs.${data.aws_region.current.name}.amazonaws.com" }
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
            "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
          }
        }
      },
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-portal-ec2-cw-logs-cmk"
  })
}

resource "aws_kms_alias" "cloudwatch_logs" {
  name          = "alias/${var.name_prefix}-portal-ec2-cw-logs"
  target_key_id = aws_kms_key.cloudwatch_logs.key_id
}
