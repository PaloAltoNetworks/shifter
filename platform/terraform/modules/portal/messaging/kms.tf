# Portal-Messaging Module - Customer-Managed KMS Key
#
# CMK for SNS topic + SQS queues (Checkov CKV_AWS_27, CKV_AWS_26). The same
# key encrypts both the SNS topic and every SQS queue so SNS→SQS fan-out
# stays in-band; the key policy grants both AWS services the operations they
# need and lets SNS deliver to the encrypted SQS queues.

data "aws_caller_identity" "kms_account" {}

resource "aws_kms_key" "messaging" {
  description             = "CMK for shifter portal-messaging SNS/SQS (CKV_AWS_26, CKV_AWS_27)"
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
        Sid       = "AllowSNSPublishToEncryptedSQS"
        Effect    = "Allow"
        Principal = { Service = "sns.amazonaws.com" }
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.kms_account.account_id
          }
        }
      },
      {
        Sid       = "AllowSQSService"
        Effect    = "Allow"
        Principal = { Service = "sqs.amazonaws.com" }
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.kms_account.account_id
          }
        }
      },
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-portal-messaging-cmk"
  })
}

resource "aws_kms_alias" "messaging" {
  name          = "alias/${var.name_prefix}-portal-messaging"
  target_key_id = aws_kms_key.messaging.key_id
}
