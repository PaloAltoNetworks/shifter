# Engine-Provisioner Module - Customer-Managed KMS Key
#
# CMK for the engine-provisioner CloudWatch log group (Checkov CKV_AWS_158).
# Scoped so the CloudWatch Logs service in this region can encrypt/decrypt log
# events while every other use of the key requires explicit grants.

resource "aws_kms_key" "cloudwatch_logs" {
  description             = "CMK for shifter engine-provisioner CloudWatch logs (CKV_AWS_158)"
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
    Name = "${var.name_prefix}-engine-provisioner-cw-logs-cmk"
  })
}

resource "aws_kms_alias" "cloudwatch_logs" {
  name          = "alias/${var.name_prefix}-engine-provisioner-cw-logs"
  target_key_id = aws_kms_key.cloudwatch_logs.key_id
}
